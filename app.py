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
# 期待する列定義（ここを固定してズレを防ぐ）
EXPECTED_COLS = ["type", "id", "name", "extra", "pass"]

def clean_numeric_str(val):
    """
    数値として読み込まれてしまったIDやパスワードを綺麗な文字列にする
    例: 1234.0 -> "1234", "001" -> "001"
    """
    s = str(val).strip()
    if s == "nan" or s == "None":
        return ""
    # ".0" で終わる場合は削除（スプシの仕様対策）
    if s.endswith(".0"):
        return s[:-2]
    return s

def load_data(conn):
    """データの読み込みと初期クリーニング"""
    try:
        # キャッシュを使わずに毎回最新を取得 (ttl=0)
        df_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=0)
        df_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=0)
        df_members = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Members", ttl=0)
        
        # --- データクリーニング (Excel/数値の変換ブレ対策) ---
        
        # 1. Config
        if not df_config.empty:
            df_config = df_config.fillna("").astype(str)
            
        # 2. Responses
        if not df_responses.empty:
            for col in ['user_id', 'slot_id']:
                if col in df_responses.columns:
                    df_responses[col] = df_responses[col].apply(clean_numeric_str)
                    
        # 3. Members
        if not df_members.empty:
            for col in ['user_id', 'password', 'name', 'bands']:
                if col in df_members.columns:
                    df_members[col] = df_members[col].apply(clean_numeric_str)

        return df_config.copy(), df_responses.copy(), df_members.copy()
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def save_data(conn, sheet_name, df):
    """
    データの保存（標準update使用・整形済みなので安全）
    """
    try:
        # 1. データを文字列化し、NaNを埋める
        df_clean = df.fillna("").astype(str)
        
        # 2. 標準のconn.updateを使用
        # 以前のエラー原因（列ズレ・型エラー）はmain関数側で排除済みのため
        # ここは標準機能を使うのが最も安全です。
        conn.update(spreadsheet=SPREADSHEET_URL, worksheet=sheet_name, data=df_clean)
        
        return True 
        
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def parse_schedule_text(text):
    """テキスト解析"""
    if not text:
        return []

    lines = text.splitlines()
    candidates = []
    current_date = None
    
    # 正規表現（日付）
    date_pattern = re.compile(r'(\d{1,4}/\d{1,2}(?:/\d{1,2})?)(?:\(.*\))?\s*(.*)')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = date_pattern.match(line)
        if match:
            current_date = match.group(1)
            time_part = match.group(2).strip()
            if time_part:
                candidates.append(f"{current_date} {time_part}")
        elif current_date:
            candidates.append(f"{current_date} {line}")
        else:
            candidates.append(line)

    return candidates

def main():
    st.set_page_config(page_title="日調アプリ", layout="wide")
    
    # CSS
    st.markdown("""
    <style>
        .stRadio > label {font-size: 1.2rem; font-weight:bold;}
        .stButton > button {width: 100%; height: 3em; font-weight:bold;}
    </style>
    """, unsafe_allow_html=True)

    st.title("日調用アプリケーション")

    # 接続
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_config, df_responses, df_members = load_data(conn)

    menu = st.sidebar.radio("メニュー", ["👤 メンバー用 (入力・確認)", "⚙️ 管理者用 (設定)"])

    # ==========================================
    # ⚙️ 管理者モード
    # ==========================================
    if menu == "⚙️ 管理者用 (設定)":
        st.header("管理者設定画面")
        password = st.text_input("管理者パスワードを入力", type="password")
        
        if password == ADMIN_PASSWORD:
            st.success("ログイン成功")
            
            st.subheader("日程枠の管理")
            
            current_slots = []
            
            # データフレーム初期化（空の場合の対策）
            if df_config.empty:
                 df_config = pd.DataFrame(columns=EXPECTED_COLS)
            
            # 列定義の強制補正
            # (スプレッドシート側で列が足りない・名前が違う場合、強制的にプログラム側の定義に合わせる)
            if not set(EXPECTED_COLS).issubset(df_config.columns):
                if len(df_config.columns) >= len(EXPECTED_COLS):
                      current_cols = list(df_config.columns)
                      new_cols = EXPECTED_COLS + current_cols[len(EXPECTED_COLS):]
                      df_config.columns = new_cols
            
            # データの抽出
            if set(EXPECTED_COLS).issubset(df_config.columns):
                mask = df_config['type'] == 'slot'
                current_slots = df_config[mask].to_dict('records')
            
            if current_slots:
                st.write("▼ 現在登録中の日程:")
                st.table(pd.DataFrame(current_slots)[['name']])
            else:
                st.info("日程が登録されていません")

            # --- 一括入力フォーム ---
            st.write("---")
            st.subheader("日程の一括追加")
            
            with st.form("add_slot_bulk"):
                placeholder_text = """12/13(土) 10:00-11:00
11:00-12:00
12/14(日) 13:00-14:00"""
                candidate_text = st.text_area(
                    "候補日程を入力（調整さん形式）", 
                    height=200, 
                    placeholder=placeholder_text
                )
                
                preview_list = parse_schedule_text(candidate_text)
                if preview_list:
                    st.caption(f"▼ 追加される日程 ({len(preview_list)}件):")
                    st.caption(", ".join(preview_list))
                
                submit_slot = st.form_submit_button("日程を一括追加する")
            
            if submit_slot:
                if not preview_list:
                    st.error("日程を認識できませんでした。入力形式を確認してください。")
                else:
                    new_rows = []
                    for cand in preview_list:
                        new_id = f"s_{uuid.uuid4().hex}"
                        new_row = {
                            "type": "slot", 
                            "id": new_id, 
                            "name": cand, 
                            "extra": "", 
                            "pass": ""
                        }
                        new_rows.append(new_row)
                    
                    # ベースデータ作成
                    if set(EXPECTED_COLS).issubset(df_config.columns):
                        base_df = df_config[EXPECTED_COLS].copy()
                    else:
                        base_df = pd.DataFrame(columns=EXPECTED_COLS)
                    
                    # 結合
                    new_df = pd.DataFrame(new_rows)
                    final_df = pd.concat([base_df, new_df], ignore_index=True)

                    # 保存
                    if save_data(conn, "Config", final_df):
                        st.success(f"{len(new_rows)} 件を追加しました！")
                        st.cache_data.clear()
                        time.sleep(1.0)
                        st.rerun()

            # リセットボタン
            st.write("---")
            if st.button("全日程を削除してリセットする", type="primary"):
                # ヘッダーのみの空DFを作成して上書き
                empty_df = pd.DataFrame(columns=EXPECTED_COLS)
                if save_data(conn, "Config", empty_df):
                    st.warning("日程を全て削除し、シートを初期化しました")
                    time.sleep(1.0)
                    st.rerun()

    # ==========================================
    # 👤 メンバーモード
    # ==========================================
    else: 
        if df_members.empty:
            st.warning("メンバーが登録されていません。")
        else:
            users = df_members.to_dict('records')
            user_map = {u['name']: u for u in users if 'name' in u and u['name']}
            
            st.subheader("ログイン")
            col1, col2 = st.columns([2, 1])
            
            if not user_map:
                st.error("メンバーが見つかりません(Membersシートを確認してください)")
            else:
                selected_name = col1.selectbox("名前", options=list(user_map.keys()))
                input_pass = col2.text_input("パスワード", type="password")

                current_user = user_map.get(selected_name)
                
                # パスワード照合
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
                            st.info("日程がありません")
                        else:
                            with st.form("schedule_form"):
                                input_data = []
                                for slot in slots:
                                    # 既存回答取得
                                    default_idx = 2
                                    if not df_responses.empty and {'user_id','slot_id','status'}.issubset(df_responses.columns):
                                        prev = df_responses[
                                            (df_responses['user_id'] == current_user['user_id']) & 
                                            (df_responses['slot_id'] == slot['id'])
                                        ]
                                        if not prev.empty:
                                            try:
                                                default_idx = STATUS_OPTIONS.index(prev.iloc[0]['status'])
                                            except: pass
                                    
                                    val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                                    input_data.append({"user_id": current_user['user_id'], "slot_id": slot['id'], "status": val})
                                
                                if st.form_submit_button("保存する", type="primary"):
                                    new_input_df = pd.DataFrame(input_data)
                                    
                                    # 既存データを保持しつつ更新
                                    other_df = pd.DataFrame(columns=["user_id", "slot_id", "status"])
                                    if not df_responses.empty and {'user_id','slot_id','status'}.issubset(df_responses.columns):
                                         mask = df_responses['user_id'] != current_user['user_id']
                                         other_df = df_responses[mask]

                                    final_res = pd.concat([other_df, new_input_df], ignore_index=True)
                                    
                                    if save_data(conn, "Responses", final_res):
                                        st.toast("保存しました！")
                                        time.sleep(0.5)
                                        st.rerun()

                    elif mode == "🔍 バンドの予定を見る":
                        st.subheader("🔍 確認")
                        my_bands_str = current_user.get('bands', '')
                        my_bands = [b.strip() for b in my_bands_str.replace(" ", "").split(",") if b.strip()]
                        
                        if not my_bands:
                            st.warning("バンド所属情報がありません")
                        else:
                            target = st.selectbox("バンドを選択", my_bands)
                            if target:
                                members = [u for u in users if target in str(u.get('bands', '')).split(",")]
                                st.info(f"メンバー: {', '.join([m['name'] for m in members])}")
                                
                                # 回答マップ作成
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
                                    st.dataframe(pd.DataFrame(view_data), hide_index=True)
                                else:
                                    st.warning("表示するデータがありません")
                
                elif input_pass:
                    st.error("パスワードが違います")
                else:
                    st.info("パスワードを入力してください")

if __name__ == "__main__":
    main()