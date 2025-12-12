import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

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
        # 3. メンバー名簿 (Membersシート) ★新規追加
        df_members = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Members", ttl=5)
        
        return df_config, df_responses, df_members
    except Exception:
        # シートがない場合などの安全策
        return pd.DataFrame(), pd.DataFrame(columns=["user_id", "slot_id", "status"]), pd.DataFrame()

def save_data(conn, sheet_name, df):
    """データの保存"""
    conn.update(spreadsheet=SPREADSHEET_URL, worksheet=sheet_name, data=df)

def main():
    st.set_page_config(page_title="バンド日程調整", layout="wide", page_icon="🎸")
    
    # CSSでスマホでも見やすく調整
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
            
            # ★変更点: Excelアップロード機能を削除し、案内を表示
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
            
            # 新規追加フォーム
            with st.form("add_slot"):
                col1, col2 = st.columns(2)
                date_val = col1.date_input("日付")
                time_val = col2.text_input("時間帯 (例: 18:00-21:00)")
                submit_slot = st.form_submit_button("日程を追加する")
                
                if submit_slot:
                    new_label = f"{date_val.month}/{date_val.day}({date_val.strftime('%a')}) {time_val}"
                    new_id = f"s_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    # Configシートは「日程(slot)」専用として使う
                    new_row = {"type": "slot", "id": new_id, "name": new_label, "extra": "", "pass": ""}
                    updated_df = pd.concat([df_config, pd.DataFrame([new_row])], ignore_index=True)
                    save_data(conn, "Config", updated_df)
                    st.success(f"「{new_label}」を追加しました！")
                    st.rerun()

            # リセットボタン
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
        # ★変更点: Membersシートからデータを取得
        if df_members.empty:
            st.warning("メンバーが登録されていません。管理者はスプレッドシートの `Members` シートに入力してください。")
            return

        # ユーザー辞書の作成 (型変換でエラーを防ぐ)
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
        
        # パスワード処理 (.0対策)
        input_pass_clean = str(input_pass).strip()
        stored_pass = str(current_user.get('password', '')).strip() # 列名が 'password' になりました
        if stored_pass.endswith('.0'):
            stored_pass = stored_pass[:-2]

        if current_user and input_pass_clean and stored_pass == input_pass_clean:
            st.success(f"ようこそ、{selected_name} さん！")
            
            # 日程データの取得
            slots = []
            if not df_config.empty:
                slots = df_config[df_config['type'] == 'slot'].to_dict('records')

            st.write("---") 
            
            # 画面切り替えボタン
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
                            # 既存の回答を探す (user_id と slot_id で検索)
                            prev = df_responses[
                                (df_responses['user_id'] == current_user['user_id']) & 
                                (df_responses['slot_id'] == slot['id'])
                            ]
                            default_idx = 2 # ？
                            if not prev.empty:
                                try:
                                    default_idx = STATUS_OPTIONS.index(prev.iloc[0]['status'])
                                except: pass
                            
                            val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                            input_data.append({"user_id": current_user['user_id'], "slot_id": slot['id'], "status": val})
                        
                        if st.form_submit_button("保存する", type="primary"):
                            new_df = pd.DataFrame(input_data)
                            # 自分以外のデータを残して保存
                            other_data = df_responses[df_responses['user_id'] != current_user['user_id']]
                            final_df = pd.concat([other_data, new_df], ignore_index=True)
                            save_data(conn, "Responses", final_df)
                            st.toast("✅ 予定を保存しました！", icon="🎉")
                            st.rerun()

            # --- 確認画面 ---
            elif mode == "🔍 バンドの予定を見る":
                st.subheader("🔍 スケジュール確認")
                
                # 所属バンドの取得 (列名は 'bands')
                my_bands_str = str(current_user.get('bands', '')).replace(" ", "")
                
                if my_bands_str and my_bands_str != "nan":
                    my_bands = my_bands_str.split(",")
                    target_band = st.selectbox("確認したいバンドを選択", my_bands)
                    
                    if target_band:
                        # Membersシートから同じバンドの人を検索
                        band_members = [
                            u for u in users 
                            if target_band in str(u.get('bands', '')).replace(" ", "").split(",")
                        ]
                        
                        st.info(f"メンバー: {', '.join([u['name'] for u in band_members])}")
                        
                        # 表の作成
                        view_rows = []
                        r_map = {}
                        for _, r in df_responses.iterrows():
                            # IDの型を文字列に統一してキーにする
                            r_map[(str(r['user_id']), str(r['slot_id']))] = r['status']

                        for slot in slots:
                            row_data = {"日程": slot['name']}
                            all_ok = True
                            has_ng = False
                            
                            for member in band_members:
                                # マップから取得
                                stt = r_map.get((str(member['user_id']), str(slot['id'])), "？")
                                row_data[member['name']] = stt
                                if stt != "〇": all_ok = False
                                if stt == "×": has_ng = True
                            
                            if has_ng: row_data["判定"] = "✕"
                            elif all_ok: row_data["判定"] = "◎"
                            else: row_data["判定"] = "△"
                            
                            view_rows.append(row_data)
                        
                        st.dataframe(pd.DataFrame(view_rows), hide_index=True, use_container_width=True)
                else:
                    st.warning("所属バンドが登録されていません。")

        elif input_pass:
            st.error("パスワードが違います")
        else:
            st.info("パスワードを入力してください")

if __name__ == "__main__":
    main()