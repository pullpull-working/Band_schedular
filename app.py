import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

# ==========================================
# ▼ 設定エリア: Secretsから読み込む
# ==========================================
# st.secrets という辞書から値を取り出します
SPREADSHEET_URL = st.secrets["spreadsheet_url"]
ADMIN_PASSWORD = st.secrets["admin_password"]
# ==========================================

# 定数定義
STATUS_OPTIONS = ["〇", "△", "？", "×"]

def load_data(conn):
    """データの読み込み"""
    # 5秒間はキャッシュを使う（連打対策）
    df_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=5)
    df_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=5)
    return df_config, df_responses

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
    df_config, df_responses = load_data(conn)

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
            
            tab1, tab2 = st.tabs(["📅 日程枠の作成", "👥 メンバー登録"])

            # --- 日程枠管理 ---
            with tab1:
                st.subheader("1. 練習候補日の登録")
                st.write("現在登録されている日程:")
                
                # 現在のスロットを取得
                current_slots = []
                if not df_config.empty:
                    current_slots = df_config[df_config['type'] == 'slot'].to_dict('records')
                    if current_slots:
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

            # --- メンバー管理 ---
            with tab2:
                st.subheader("2. メンバー・バンドの一括登録")
                st.markdown("Excelファイルをアップロードして、名簿を一括更新します。")
                st.info("Excelの列名: `名前`, `パスワード`, `所属バンド` (カンマ区切り)")
                
                uploaded_file = st.file_uploader("Excelファイルをドラッグ&ドロップ", type=['xlsx'])
                
                if uploaded_file and st.button("名簿を更新する"):
                    try:
                        # Excel読み込み
                        df_excel = pd.read_excel(uploaded_file)
                        
                        # 新しいConfigデータを作成
                        new_rows = []
                        
                        # 1. ユーザーデータの作成
                        for i, row in df_excel.iterrows():
                            uid = f"u_{i+1:03}" # u_001, u_002...
                            p_bands = str(row['所属バンド']).replace(" ", "").split(",")
                            
                            # ユーザー行
                            new_rows.append({
                                "type": "user", 
                                "id": uid, 
                                "name": row['名前'], 
                                "extra": row['所属バンド'], # 所属バンド名をメモ
                                "pass": str(row['パスワード'])
                            })
                            
                            # グループ情報の自動生成（バンド名 -> メンバーIDリスト）
                            # ※ここでは簡易的に、あとで集計処理を行うためユーザー情報だけ持てばOKとする
                        
                        # 既存のslotデータは残す
                        if not df_config.empty:
                            slot_rows = df_config[df_config['type'] == 'slot'].to_dict('records')
                            new_rows.extend(slot_rows)
                            
                        # 保存
                        save_data(conn, "Config", pd.DataFrame(new_rows))
                        st.success("名簿を更新しました！")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"エラーが発生しました: {e}")

        elif password:
            st.error("パスワードが違います")

    # ==========================================
    # 👤 メンバーモード (GUI)
    # ==========================================
    else: # メンバー用
        if df_config.empty:
            st.warning("管理者がまだ設定を行っていません。")
            return

        # ユーザー辞書の作成
        users = df_config[df_config['type'] == 'user'].to_dict('records')
        user_map = {u['name']: u for u in users}
        
        # ログイン画面
        st.subheader("ログイン")
        col1, col2 = st.columns([2, 1])
        selected_name = col1.selectbox("名前を選んでください", options=list(user_map.keys()))
        input_pass = col2.text_input("パスワード(数字)", type="password")

        # 認証ロジック
        current_user = user_map.get(selected_name)
        
        # 画面に入力されたパスワードをきれいにする（空白削除）
        input_pass_clean = str(input_pass).strip()

        # スプレッドシートのパスワードをきれいにする
        # 1. 文字列にする
        # 2. ".0" がついていたら消す (1234.0 -> 1234)
        # 3. 前後の空白を消す
        stored_pass = str(current_user.get('pass', '')).strip()
        if stored_pass.endswith('.0'):
            stored_pass = stored_pass[:-2]

        # デバッグ用: もしこれで直らなかったら、下の行の # を消して画面に表示させてみてください
        # st.write(f"保存されているPW: '{stored_pass}' vs 入力したPW: '{input_pass_clean}'")

        if current_user and stored_pass == input_pass_clean:
            st.success(f"ようこそ、{selected_name} さん！")
            
            # (以下、タブ表示のコードなどはそのまま...)
            
            # タブ: 入力 / 確認
            tab_in, tab_view = st.tabs(["📝 予定を入れる", "🔍 バンドの予定を見る"])
            
            slots = df_config[df_config['type'] == 'slot'].to_dict('records')
            
            # --- 入力タブ ---
            with tab_in:
                st.write("以下の日程について、都合を選択して「保存」を押してください。")
                with st.form("schedule_form"):
                    input_data = []
                    for slot in slots:
                        # 既存の回答を探す
                        key = (current_user['id'], slot['id'])
                        # response_mapを作るのが重いので、簡易フィルタ
                        prev = df_responses[
                            (df_responses['user_id'] == current_user['id']) & 
                            (df_responses['slot_id'] == slot['id'])
                        ]
                        default_idx = 2 #
                        if not prev.empty:
                            try:
                                default_idx = STATUS_OPTIONS.index(prev.iloc[0]['status'])
                            except: pass
                        
                        val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                        input_data.append({"user_id": current_user['id'], "slot_id": slot['id'], "status": val})
                    
                    if st.form_submit_button("保存する"):
                        # データ更新処理
                        new_df = pd.DataFrame(input_data)
                        # 自分以外のデータを残す
                        other_data = df_responses[df_responses['user_id'] != current_user['id']]
                        final_df = pd.concat([other_data, new_df], ignore_index=True)
                        save_data(conn, "Responses", final_df)
                        st.toast("✅ 予定を保存しました！", icon="🎉")
                        st.rerun()

            # --- 確認タブ ---
            with tab_view:
                st.write("所属しているバンドの状況を確認できます。")
                
                # 自分の所属バンドリストを取得
                my_bands = str(current_user['extra']).replace(" ", "").split(",")
                target_band = st.selectbox("確認したいバンド", my_bands)
                
                if target_band:
                    # そのバンドに所属するメンバーIDを探す
                    # (Configのextra列にバンド名が含まれているか検索)
                    band_members = [
                        u for u in users 
                        if target_band in str(u['extra']).replace(" ", "").split(",")
                    ]
                    
                    st.markdown(f"### {target_band} のスケジュール")
                    st.caption(f"メンバー: {', '.join([u['name'] for u in band_members])}")
                    
                    # 閲覧用データの作成
                    view_rows = []
                    # 最新の回答マップ再構築
                    r_map = {}
                    for _, r in df_responses.iterrows():
                        r_map[(r['user_id'], r['slot_id'])] = r['status']

                    for slot in slots:
                        row_data = {"日程": slot['name']}
                        all_ok = True
                        has_ng = False
                        
                        for member in band_members:
                            stt = r_map.get((member['id'], slot['id']), "？")
                            row_data[member['name']] = stt
                            if stt != "〇": all_ok = False
                            if stt == "×": has_ng = True
                        
                        if has_ng: row_data["判定"] = "❌"
                        elif all_ok: row_data["判定"] = "🎯"
                        else: row_data["判定"] = "⚠️"
                        
                        view_rows.append(row_data)
                    
                    # 表示
                    st.dataframe(pd.DataFrame(view_rows), hide_index=True, use_container_width=True)

        elif input_pass:
            st.error("パスワードが違います")
        else:
            st.info("パスワードを入力してください")

if __name__ == "__main__":
    main()