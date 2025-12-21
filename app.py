import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import re
import uuid
import time 

# ==========================================
# ▼ 設定エリア
# ==========================================
SPREADSHEET_URL = st.secrets["spreadsheet_url"]
ADMIN_PASSWORD = st.secrets["admin_password"]

STATUS_OPTIONS = ["〇", "△", "？", "×"]
EXPECTED_COLS = ["type", "id", "name", "extra", "pass"]

# ==========================================
# ▼ 関数定義
# ==========================================

def is_quota_error(e):
    """エラーがAPI制限(429)かどうかを判定する"""
    msg = str(e).lower()
    return "quota exceeded" in msg or "429" in msg or "resource_exhausted" in msg

def clean_numeric_str(val):
    """数値のクリーニング"""
    s = str(val).strip()
    if s.lower() in ["nan", "none", ""]:
        return ""
    if s.endswith(".0"):
        return s[:-2]
    return s

def load_data(conn):
    """データの読み込み（API制限対策済み）"""
    df_config = pd.DataFrame()
    df_responses = pd.DataFrame()
    df_members = pd.DataFrame()

    # 各読み込みの間にsleepを入れて制限回避を試みる
    try:
        df_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=0)
        if not df_config.empty:
            df_config = df_config.fillna("").astype(str)
    except Exception:
        pass 
    
    time.sleep(1.0) 

    try:
        df_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=0)
        if not df_responses.empty:
            for col in ['user_id', 'slot_id']:
                if col in df_responses.columns:
                    df_responses[col] = df_responses[col].apply(clean_numeric_str)
    except Exception:
        pass 
    
    time.sleep(1.0)

    try:
        df_members = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Members", ttl=0)
        if not df_members.empty:
            for col in ['user_id', 'password', 'name', 'bands']:
                if col in df_members.columns:
                    df_members[col] = df_members[col].apply(clean_numeric_str)
    except Exception as e:
        # ★ここを修正: エラー内容によって表示を変える
        if is_quota_error(e):
            st.warning("現在アクセスが込み合っています。しばらく待ってから再読み込みしてください。")
        else:
            st.error(f"メンバー表の読み込みに失敗しました: {e}")

    return df_config.copy(), df_responses.copy(), df_members.copy()

def save_data(conn, sheet_name, df):
    """データの保存（API制限時は優しいメッセージを表示）"""
    try:
        df_clean = df.fillna("").astype(str)
        try:
            conn.update(worksheet=sheet_name, data=df_clean)
            time.sleep(1.0) 
            return True
        except Exception:
            try:
                conn.update(spreadsheet=SPREADSHEET_URL, worksheet=sheet_name, data=df_clean)
                time.sleep(1.0) 
                return True
            except Exception as inner_e:
                raise inner_e
    except Exception as e:
        # ★ここを修正: API制限エラーの場合は優しいメッセージにする
        if is_quota_error(e):
            st.warning("込み合っています。しばらく待ってから試してね。")
            return False
            
        err_msg = str(e)
        if "not found" in err_msg.lower() or "見つかりません" in err_msg:
            st.error(f"エラー: シート '{sheet_name}' が見つかりません。")
        else:
            st.error(f"保存中にエラーが発生しました: {e}")
        return False

def parse_schedule_text(text):
    """単純な行ごとの解析"""
    if not text:
        return []
    lines = text.splitlines()
    candidates = [line.strip() for line in lines if line.strip()]
    return candidates

# ==========================================
# ▼ メイン処理
# ==========================================

def main():
    st.set_page_config(page_title="バンド日調アプリ", layout="wide", page_icon="🎤")
    
    st.markdown("""
        <style>
        footer {visibility: hidden;}
        .stDeployButton {display:none;}
        .stRadio > label {font-size: 1.2rem; font-weight:bold;}
        .stButton > button {width: 100%; height: 3em; font-weight:bold;}
        div[data-testid="stRadio"] {
            padding-bottom: 10px;
            border-bottom: 1px solid #f0f2f6;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("日調用アプリケーション")

    conn = st.connection("gsheets", type=GSheetsConnection)
    df_config, df_responses, df_members = load_data(conn)

    menu = st.sidebar.radio("メニュー", ["👤 メンバー用 (入力・確認)", "⚙️ 管理者用 (設定)"])

    # ------------------------------------------
    # ⚙️ 管理者モード
    # ------------------------------------------
    if menu == "⚙️ 管理者用 (設定)":
        st.header("管理者設定画面")
        password = st.text_input("管理者パスワードを入力", type="password")
        
        if password == ADMIN_PASSWORD:
            st.success("ログイン成功")
            
            st.subheader("登録済み日程一覧")
            
            current_slots = []
            if df_config.empty:
                 df_config = pd.DataFrame(columns=EXPECTED_COLS)
            
            if not set(EXPECTED_COLS).issubset(df_config.columns):
                if len(df_config.columns) >= len(EXPECTED_COLS):
                      current_cols = list(df_config.columns)
                      new_cols = EXPECTED_COLS + current_cols[len(EXPECTED_COLS):]
                      df_config.columns = new_cols
            
            if set(EXPECTED_COLS).issubset(df_config.columns):
                mask = df_config['type'] == 'slot'
                current_slots = df_config[mask].to_dict('records')
            
            if current_slots:
                st.table(pd.DataFrame(current_slots)[['name']])
            else:
                st.info("日程が登録されていません")

            st.write("---")
            st.subheader("日程の一括追加")
            with st.form("add_slot_bulk"):
                placeholder_text = """12/13(土) 10:00-11:00
11:00-12:00
12/14(日) 13:00-14:00"""
                candidate_text = st.text_area("テキスト貼り付けで追加", height=150, placeholder=placeholder_text)
                submit_slot = st.form_submit_button("追加する")
            
            if submit_slot:
                fresh_config = pd.DataFrame()
                try:
                    fresh_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=0)
                    if not fresh_config.empty:
                        fresh_config = fresh_config.fillna("").astype(str)
                except:
                    pass

                if fresh_config.empty and not df_config.empty:
                    fresh_config = df_config.copy() 

                preview_list = parse_schedule_text(candidate_text)
                if not preview_list:
                    st.error("日程を認識できませんでした。")
                else:
                    new_rows = []
                    for cand in preview_list:
                        new_rows.append({
                            "type": "slot", "id": f"s_{uuid.uuid4().hex}", "name": cand, "extra": "", "pass": ""
                        })
                    new_df = pd.DataFrame(new_rows)
                    
                    if set(EXPECTED_COLS).issubset(fresh_config.columns):
                        base_df = fresh_config[EXPECTED_COLS].copy()
                    else:
                        base_df = pd.DataFrame(columns=EXPECTED_COLS)
                        
                    final_df = pd.concat([base_df, new_df], ignore_index=True)

                    if save_data(conn, "Config", final_df):
                        st.success(f"{len(new_rows)} 件を追加しました！")
                        st.cache_data.clear()
                        time.sleep(1.0)
                        st.rerun()

            st.write("---")
            st.subheader("日程のリセット")
            st.caption("※ 注意：日程だけでなく、メンバーが入力した回答データも全て消去されます。")
            if st.button("全日程・全回答を削除してリセットする", type="primary"):
                empty_config = pd.DataFrame(columns=EXPECTED_COLS)
                empty_responses = pd.DataFrame(columns=["user_id", "slot_id", "status"])
                
                success_config = save_data(conn, "Config", empty_config)
                time.sleep(1.0)
                success_res = save_data(conn, "Responses", empty_responses)
                
                if success_config and success_res:
                    st.warning("日程と回答を全て削除し、初期化しました")
                    time.sleep(1.0)
                    st.rerun()
                else:
                    # save_data側でエラー表示済みなのでここではシンプルに
                    pass

    # ------------------------------------------
    # 👤 メンバーモード
    # ------------------------------------------
    else: 
        if df_members.empty:
            # ここもエラーではなくWarningにしておく
            st.warning("データの読み込みに時間がかかっています。少し待ってからリロードしてください。")
        else:
            users = df_members.to_dict('records')
            user_map = {u['name']: u for u in users if u.get('name')}
            
            st.subheader("ログイン")
            col1, col2 = st.columns([2, 1])
            
            if not user_map:
                st.error("有効なメンバーが見つかりません。")
            else:
                selected_name = col1.selectbox("名前", options=list(user_map.keys()))
                input_pass = col2.text_input("パスワード", type="password")

                current_user = user_map.get(selected_name)
                p_in = str(input_pass).strip()
                p_store = str(current_user.get('password', ''))
                
                if current_user and p_in and p_store == p_in:
                    st.success(f"ようこそ {selected_name} さん")
                    
                    slots = []
                    if not df_config.empty and set(EXPECTED_COLS).issubset(df_config.columns):
                        mask = df_config['type'] == 'slot'
                        slots = df_config[mask].to_dict('records')

                    st.write("---")
                    mode = st.radio("モード", ["📝 予定を入れる", "🔍 バンドの予定を見る"], horizontal=True)

                    if mode == "📝 予定を入れる":
                        st.subheader("📝 予定の入力")
                        
                        if not slots:
                            st.info("現在、調整中の日程はありません。")
                        else:
                            with st.form("schedule_form"):
                                input_data = []
                                for slot in slots:
                                    default_idx = 2
                                    if not df_responses.empty and {'user_id','slot_id','status'}.issubset(df_responses.columns):
                                        prev = df_responses[
                                            (df_responses['user_id'] == str(current_user['user_id'])) & 
                                            (df_responses['slot_id'] == str(slot['id']))
                                        ]
                                        if not prev.empty:
                                            try:
                                                val = prev.iloc[0]['status']
                                                default_idx = STATUS_OPTIONS.index(val)
                                            except: pass
                                    
                                    val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                                    input_data.append({"user_id": str(current_user['user_id']), "slot_id": str(slot['id']), "status": val})
                                
                                # 保存ボタン
                                if st.form_submit_button("回答を保存する", type="primary"):
                                    fresh_responses = pd.DataFrame()
                                    try:
                                        fresh_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=0)
                                        if not fresh_responses.empty:
                                             for col in ['user_id', 'slot_id']:
                                                if col in fresh_responses.columns:
                                                    fresh_responses[col] = fresh_responses[col].apply(clean_numeric_str)
                                    except: pass
                                    
                                    if fresh_responses.empty and not df_responses.empty:
                                        fresh_responses = df_responses.copy()
                                    elif fresh_responses.empty:
                                        fresh_responses = pd.DataFrame(columns=["user_id", "slot_id", "status"])

                                    new_input_df = pd.DataFrame(input_data)
                                    other_df = pd.DataFrame(columns=["user_id", "slot_id", "status"])
                                    
                                    if not fresh_responses.empty and {'user_id','slot_id','status'}.issubset(fresh_responses.columns):
                                         clean_uid = str(current_user['user_id'])
                                         mask = fresh_responses['user_id'] != clean_uid
                                         other_df = fresh_responses[mask]

                                    final_res = pd.concat([other_df, new_input_df], ignore_index=True)
                                    
                                    if save_data(conn, "Responses", final_res):
                                        st.toast("回答を更新しました！")
                                        time.sleep(1.0)
                                        st.rerun()

                            st.write("")
                            st.write("---")
                            st.caption("※ 間違えて入力した場合など、最初からやり直したい時はこちら")
                            if st.button("自分の回答を全て削除する"):
                                fresh_responses = pd.DataFrame()
                                try:
                                    fresh_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=0)
                                    if not fresh_responses.empty:
                                         for col in ['user_id', 'slot_id']:
                                            if col in fresh_responses.columns:
                                                fresh_responses[col] = fresh_responses[col].apply(clean_numeric_str)
                                except: pass
                                
                                if not fresh_responses.empty and 'user_id' in fresh_responses.columns:
                                    clean_uid = str(current_user['user_id'])
                                    new_df = fresh_responses[fresh_responses['user_id'] != clean_uid]
                                    
                                    if save_data(conn, "Responses", new_df):
                                        st.warning("回答を全て削除（リセット）しました。")
                                        time.sleep(1.0)
                                        st.rerun()
                                else:
                                    st.warning("削除するデータがありません。")

                    elif mode == "🔍 バンドの予定を見る":
                        st.subheader("🔍 確認")
                        my_bands_str = current_user.get('bands', '')
                        my_bands = [b.strip() for b in my_bands_str.split(",") if b.strip()]
                        
                        if not my_bands:
                            st.warning("バンド所属情報が登録されていません。")
                        else:
                            target = st.selectbox("バンドを選択", my_bands)
                            if target:
                                members = []
                                for u in users:
                                    u_bands = [b.strip() for b in str(u.get('bands', '')).split(",")]
                                    if target in u_bands:
                                        members.append(u)
                                
                                st.info(f"メンバー: {', '.join([m['name'] for m in members])}")
                                
                                r_map = {}
                                if not df_responses.empty and {'user_id','slot_id','status'}.issubset(df_responses.columns):
                                    for _, r in df_responses.iterrows():
                                        r_map[(r['user_id'], r['slot_id'])] = r['status']
                                
                                view_data = []
                                for slot in slots:
                                    row = {"日程": slot['name']}
                                    statuses = []
                                    for m in members:
                                        s = r_map.get((m['user_id'], slot['id']), "？")
                                        row[m['name']] = s
                                        statuses.append(s)
                                    
                                    if "×" in statuses: row["判定"] = "✕"
                                    elif all(s == "〇" for s in statuses): row["判定"] = "◎"
                                    elif all(s in ["〇", "△"] for s in statuses): row["判定"] = "○"
                                    else: row["判定"] = "△"
                                    
                                    view_data.append(row)
                                
                                if view_data:
                                    st.dataframe(pd.DataFrame(view_data), hide_index=True, key=f"view_{target}")
                                else:
                                    st.warning("表示するデータがありません")
                
                elif input_pass:
                    st.error("パスワードが違います")
                else:
                    st.info("パスワードを入力してください。フォームに未回答の方は https://forms.gle/bQqeozh5KhjBMzSy7 のフォームを答えてね")

if __name__ == "__main__":
    main()