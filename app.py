import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import re
import uuid

# ==========================================
# ▼ 設定エリア: Secretsから読み込む
# ==========================================
SPREADSHEET_URL = st.secrets["spreadsheet_url"]
ADMIN_PASSWORD = st.secrets["admin_password"]

# 定数定義
STATUS_OPTIONS = ["〇", "△", "？", "×"]

def load_data(conn):
    """データの読み込み"""
    try:
        # 1. 日程枠 (Configシート)
        df_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=5)
        # 2. 回答データ (Responsesシート)
        df_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=5)
        # 3. メンバー名簿 (Membersシート)
        df_members = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Members", ttl=5)
        
        return df_config, df_responses, df_members
    except Exception:
        return pd.DataFrame(), pd.DataFrame(columns=["user_id", "slot_id", "status"]), pd.DataFrame()

def save_data(conn, sheet_name, df):
    """データの保存"""
    # 【重要修正】エラー回避のため、NaN(欠損値)を空文字に変換してから保存する
    df_clean = df.fillna("")
    conn.update(spreadsheet=SPREADSHEET_URL, worksheet=sheet_name, data=df_clean)

def parse_schedule_text(text):
    """
    調整さん形式のテキストを解析して候補日程のリストを返す
    """
    if not text:
        return []

    lines = text.splitlines()
    candidates = []
    current_date = None
    
    # 正規表現: 日付(12/13など)を抽出。曜日は任意。
    date_pattern = re.compile(r'(\d{1,4}/\d{1,2}(?:/\d{1,2})?)(?:\(.*\))?\s*(.*)')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = date_pattern.match(line)
        if match:
            # 日付が見つかった行
            current_date = match.group(1)
            time_part = match.group(2).strip()
            
            if time_part:
                candidates.append(f"{current_date} {time_part}")
        
        elif current_date:
            # 日付がない行（時間のみとみなす）
            candidates.append(f"{current_date} {line}")
        else:
            # 日付がなく、いきなり時間が書かれている場合はそのまま追加
            candidates.append(line)

    return candidates

def main():
    st.set_page_config(page_title="バンド日程調整", layout="wide", page_icon="🎸")
    
    st.markdown("""
    <style>
        .stRadio > label {font-size: 1.2rem; font-weight:bold;}
        .stButton > button {width: 100%; height: 3em; font-weight:bold;}
    </style>
    """, unsafe_allow_html=True)

    st.title("🎸 バンド練習日程調整")

    # 接続確立
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_config, df_responses, df_members = load_data(conn)

    # --- メニュー切り替え ---
    menu = st.sidebar.radio("メニュー", ["👤 メンバー用 (入力・確認)", "⚙️ 管理者用 (設定)"])

    # ==========================================
    # ⚙️ 管理者モード
    # ==========================================
    if menu == "⚙️ 管理者用 (設定)":
        st.header("管理者設定画面")
        password = st.text_input("管理者パスワードを入力", type="password")
        
        if password == ADMIN_PASSWORD:
            st.success("ログイン成功")
            st.info("💡 メンバーの追加・編集・削除は、Googleスプレッドシートの **`Members`** シートを直接編集してください。")
            
            st.subheader("📅 日程枠の管理")
            
            # 現在のスロットを取得
            current_slots = []
            if not df_config.empty:
                current_slots = df_config[df_config['type'] == 'slot'].to_dict('records')
                if current_slots:
                    st.write("▼ 現在登録中の日程:")
                    st.table(pd.DataFrame(current_slots)[['name']])
                else:
                    st.info("日程が登録されていません")
            
            # --- 一括入力フォーム ---
            st.write("---")
            st.subheader("日程の一括追加")
            st.caption("調整さんのようにテキストボックスに入力してください。")

            with st.form("add_slot_bulk"):
                placeholder_text = """12/13(土) 10:00-11:00
11:00-12:00
12/14(日) 13:00-14:00"""
                candidate_text = st.text_area("候補日程を入力", height=200, placeholder=placeholder_text)
                
                submit_slot = st.form_submit_button("日程を一括追加する")
                
                if submit_slot:
                    candidates = parse_schedule_text(candidate_text)
                    
                    if not candidates:
                        st.error("日程が入力されていません")
                    else:
                        new_rows = []
                        for cand in candidates:
                            new_id = f"s_{uuid.uuid4().hex}"
                            new_row = {
                                "type": "slot", 
                                "id": new_id, 
                                "name": cand, 
                                "extra": "", 
                                "pass": ""
                            }
                            new_rows.append(new_row)
                        
                        # 結合処理
                        updated_df = pd.concat([df_config, pd.DataFrame(new_rows)], ignore_index=True)
                        
                        # 保存 (save_data内でfillnaされるので安全)
                        save_data(conn, "Config", updated_df)
                        
                        st.success(f"{len(new_rows)} 件の日程を追加しました！")
                        st.cache_data.clear() # キャッシュクリア
                        st.rerun()

            # リセットボタン
            st.write("---")
            if st.button("全日程を削除してリセットする", type="primary"):
                # slotタイプだけ削除
                new_df = df_config[df_config['type'] != 'slot']
                save_data(conn, "Config", new_df)
                st.warning("日程を全て削除しました")
                st.rerun()

    # ==========================================
    # 👤 メンバーモード (GUI)
    # ==========================================
    else: # メンバー用
        if df_members.empty:
            st.warning("メンバーが登録されていません。管理者はスプレッドシートの `Members` シートに入力してください。")
            return

        df_members['user_id'] = df_members['user_id'].astype(str)
        df_members['password'] = df_members['password'].astype(str)
        
        users = df_members.to_dict('records')
        user_map = {u['name']: u for u in users}
        
        # ログイン画面
        st.subheader("ログイン")
        col1, col2 = st.columns([2, 1])
        selected_name = col1.selectbox("名前を選んでください", options=list(user_map.keys()))
        input_pass = col2.text_input("パスワード(数字)", type="password")

        # 認証ロジック
        current_user = user_map.get(selected_name)
        input_pass_clean = str(input_pass).strip()
        stored_pass = str(current_user.get('password', '')).strip()
        if stored_pass.endswith('.0'):
            stored_pass = stored_pass[:-2]

        if current_user and input_pass_clean and stored_pass == input_pass_clean:
            st.success(f"ようこそ、{selected_name} さん！")
            
            slots = []
            if not df_config.empty:
                slots = df_config[df_config['type'] == 'slot'].to_dict('records')

            st.write("---") 
            
            mode = st.radio(
                "モード選択", 
                ["📝 予定を入れる", "🔍 バンドの予定を見る"], 
                horizontal=True,
                label_visibility="collapsed"
            )

            # --- 入力画面 ---
            if mode == "📝 予定を入れる":
                st.subheader("📝 予定の入力")
                
                if not slots:
                    st.info("現在、調整中の日程はありません。")
                else:
                    st.write("以下の日程について、都合を選択して「保存」を押してください。")
                    with st.form("schedule_form"):
                        input_data = []
                        for slot in slots:
                            prev = df_responses[
                                (df_responses['user_id'] == current_user['user_id']) & 
                                (df_responses['slot_id'] == slot['id'])
                            ]
                            default_idx = 2
                            if not prev.empty:
                                try:
                                    default_idx = STATUS_OPTIONS.index(prev.iloc[0]['status'])
                                except: pass
                            
                            val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                            input_data.append({"user_id": current_user['user_id'], "slot_id": slot['id'], "status": val})
                        
                        if st.form_submit_button("保存する", type="primary"):
                            new_df = pd.DataFrame(input_data)
                            other_data = df_responses[df_responses['user_id'] != current_user['user_id']]
                            final_df = pd.concat([other_data, new_df], ignore_index=True)
                            save_data(conn, "Responses", final_df)
                            st.toast("✅ 予定を保存しました！", icon="🎉")
                            st.rerun()

            # --- 確認画面 ---
            elif mode == "🔍 バンドの予定を見る":
                st.subheader("🔍 スケジュール確認")
                
                my_bands_str = str(current_user.get('bands', '')).replace(" ", "")
                
                if my_bands_str and my_bands_str != "nan":
                    my_bands = my_bands_str.split(",")
                    target_band = st.selectbox("確認したいバンドを選択", my_bands)
                    
                    if target_band:
                        band_members = [
                            u for u in users 
                            if target_band in str(u.get('bands', '')).replace(" ", "").split(",")
                        ]
                        
                        st.info(f"メンバー: {', '.join([u['name'] for u in band_members])}")
                        
                        view_rows = []
                        r_map = {}
                        for _, r in df_responses.iterrows():
                            r_map[(str(r['user_id']), str(r['slot_id']))] = r['status']

                        for slot in slots:
                            row_data = {"日程": slot['name']}
                            all_ok = True
                            has_ng = False
                            
                            for member in band_members:
                                stt = r_map.get((str(member['user_id']), str(slot['id'])), "？")
                                row_data[member['name']] = stt
                                if stt != "〇": all_ok = False
                                if stt == "×": has_ng = True
                            
                            if has_ng: row_data["判定"] = "✕"
                            elif all_ok: row_data["判定"] = "◎"
                            else: row_data["判定"] = "△"
                            
                            view_rows.append(row_data)
                        
                        if view_rows:
                            st.dataframe(pd.DataFrame(view_rows), hide_index=True, use_container_width=True)
                        else:
                            st.warning("日程データがありません")
                else:
                    st.warning("所属バンドが登録されていません。")

        elif input_pass:
            st.error("パスワードが違います")
        else:
            st.info("パスワードを入力してください")

if __name__ == "__main__":
    main()