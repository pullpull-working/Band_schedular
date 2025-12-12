import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import re
import uuid

# ==========================================
# ▼ 設定エリア
# ==========================================
SPREADSHEET_URL = st.secrets["spreadsheet_url"]
ADMIN_PASSWORD = st.secrets["admin_password"]

STATUS_OPTIONS = ["〇", "△", "？", "×"]
# 期待する列定義（ここを固定してズレを防ぐ）
EXPECTED_COLS = ["type", "id", "name", "extra", "pass"]

def load_data(conn):
    """データの読み込み"""
    try:
        # キャッシュを使わずに毎回最新を取得 (ttl=0)
        df_config = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Config", ttl=0)
        df_responses = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Responses", ttl=0)
        df_members = conn.read(spreadsheet=SPREADSHEET_URL, worksheet="Members", ttl=0)
        
        # コピーして安全に渡す
        return df_config.copy(), df_responses.copy(), df_members.copy()
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def save_data(conn, sheet_name, df):
    """
    データの保存（完全上書きモード）
    既存のラッパー関数の挙動が怪しいため、直接gspreadの機能を使って
    「クリア -> 全書き込み」を行います。
    """
    try:
        # 1. データを文字列化し、NaNを埋める
        df_clean = df.fillna("").astype(str)
        
        # 2. DataFrameをリスト形式（ヘッダー付き）に変換
        # gspreadはリストのリスト[[列1, 列2], [値1, 値2]...]を受け取ります
        raw_data = [df_clean.columns.tolist()] + df_clean.values.tolist()
        
        # 3. 内部のgspreadクライアントを直接操作する
        # conn.client は gspread.Client オブジェクトです
        sh = conn.client.open_by_url(SPREADSHEET_URL)
        ws = sh.worksheet(sheet_name)
        
        # 4. シートをクリアしてから書き込む（これが一番確実）
        ws.clear()
        ws.update(range_name="A1", values=raw_data)
        
    except Exception as e:
        st.error(f"データの保存中にエラーが発生しました: {e}")
        # エラー詳細をコンソールにも出す
        print(f"Save Error: {e}")

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
    st.set_page_config(page_title="バンド日程調整", layout="wide", page_icon="🎸")
    
    # CSS
    st.markdown("""
    <style>
        .stRadio > label {font-size: 1.2rem; font-weight:bold;}
        .stButton > button {width: 100%; height: 3em; font-weight:bold;}
    </style>
    """, unsafe_allow_html=True)

    st.title("🎸 バンド練習日程調整")

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
            st.info("💡 メンバーの追加・編集は `Members` シートで行ってください。")
            
            # --- 現在の日程一覧 ---
            st.subheader("📅 日程枠の管理")
            
            # データフレームの列名を強制的に修正（これが重要！）
            # スプレッドシートのヘッダーが壊れていても読み込めるようにする
            current_slots = []
            
            # もし列名が足りなければ強制的にリセットして扱う
            if df_config.empty or not set(EXPECTED_COLS).issubset(df_config.columns):
                # 列名がおかしい場合は、既存データを無理やりEXPECTED_COLSに合わせるか、
                # 空として扱う（安全策）
                if not df_config.empty and len(df_config.columns) >= 5:
                     # 列名だけすげ替える（データ救済）
                     df_config.columns = EXPECTED_COLS + list(df_config.columns)[5:]
            
            # 再度チェック
            if set(EXPECTED_COLS).issubset(df_config.columns):
                # 文字列にして空白除去してからフィルタ
                mask = df_config['type'].astype(str).str.strip() == 'slot'
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
                
                # パース結果の確認用ロジック
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
                    
                    # 1. ベースデータ作成
                    if set(EXPECTED_COLS).issubset(df_config.columns):
                        base_df = df_config[EXPECTED_COLS].copy()
                    else:
                        base_df = pd.DataFrame(columns=EXPECTED_COLS)
                    
                    # 2. 結合
                    new_df = pd.DataFrame(new_rows)
                    final_df = pd.concat([base_df, new_df], ignore_index=True)
                    
                    # --- デバッグ表示（確認用） ---
                    st.write("▼ 保存直前のデータ（これが増えていればPython側は正常です）")
                    st.dataframe(final_df.tail(5)) # 末尾5件を表示
                    # -------------------------

                    # 3. 保存 (新しい強力なsave_dataを使用)
                    save_data(conn, "Config", final_df)
                    
                    st.success(f"{len(new_rows)} 件を追加しました！")
                    st.cache_data.clear()
                    
                    # リラン前に少し待つ（Google側の反映待ち）
                    import time
                    time.sleep(1) 
                    st.rerun()

            # リセットボタン
            st.write("---")
            if st.button("全日程を削除してリセットする", type="primary"):
                # ヘッダーのみの空DFを作成して上書き（これでシートが綺麗になる）
                empty_df = pd.DataFrame(columns=EXPECTED_COLS)
                save_data(conn, "Config", empty_df)
                st.warning("日程を全て削除し、シートを初期化しました")
                st.rerun()

    # ==========================================
    # 👤 メンバーモード
    # ==========================================
    else: 
        if df_members.empty:
            st.warning("メンバーが登録されていません。")
        else:
            # データ型変換
            for col in ['user_id', 'password', 'name', 'bands']:
                if col in df_members.columns:
                    df_members[col] = df_members[col].astype(str)
            
            users = df_members.to_dict('records')
            user_map = {u['name']: u for u in users if 'name' in u and u['name'] != 'nan'}
            
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
                p_store = str(current_user.get('password', '')).strip().replace('.0', '')
                
                if current_user and p_in and p_store == p_in:
                    st.success(f"ようこそ {selected_name} さん")
                    
                    # 日程取得
                    slots = []
                    if not df_config.empty and set(EXPECTED_COLS).issubset(df_config.columns):
                        mask = df_config['type'].astype(str).str.strip() == 'slot'
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
                                        # 文字列比較
                                        prev = df_responses[
                                            (df_responses['user_id'].astype(str) == str(current_user['user_id'])) & 
                                            (df_responses['slot_id'].astype(str) == str(slot['id']))
                                        ]
                                        if not prev.empty:
                                            try:
                                                default_idx = STATUS_OPTIONS.index(prev.iloc[0]['status'])
                                            except: pass
                                    
                                    val = st.radio(f"**{slot['name']}**", STATUS_OPTIONS, index=default_idx, horizontal=True, key=slot['id'])
                                    input_data.append({"user_id": str(current_user['user_id']), "slot_id": str(slot['id']), "status": val})
                                
                                if st.form_submit_button("保存する", type="primary"):
                                    new_input_df = pd.DataFrame(input_data)
                                    
                                    # 既存データを保持しつつ更新
                                    other_df = pd.DataFrame(columns=["user_id", "slot_id", "status"])
                                    if not df_responses.empty and {'user_id','slot_id','status'}.issubset(df_responses.columns):
                                         mask = df_responses['user_id'].astype(str) != str(current_user['user_id'])
                                         other_df = df_responses[mask]

                                    final_res = pd.concat([other_df, new_input_df], ignore_index=True)
                                    save_data(conn, "Responses", final_res)
                                    st.toast("保存しました！")
                                    st.rerun()

                    elif mode == "🔍 バンドの予定を見る":
                        st.subheader("🔍 確認")
                        my_bands = str(current_user.get('bands', '')).replace(" ", "").split(",")
                        my_bands = [b for b in my_bands if b and b != 'nan']
                        
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
                                        r_map[(str(r['user_id']), str(r['slot_id']))] = r['status']
                                
                                view_data = []
                                for slot in slots:
                                    row = {"日程": slot['name']}
                                    statuses = []
                                    for m in members:
                                        s = r_map.get((str(m['user_id']), str(slot['id'])), "？")
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