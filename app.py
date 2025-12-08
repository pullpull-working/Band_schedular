import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# --- 設定: スプレッドシートの定義 ---
# 定数定義
STATUS_OPTIONS = ["〇", "△", "？", "×"]

def main():
    st.set_page_config(page_title="バンド練習日程調整", layout="wide")
    st.title("🎸 バンド練習日程調整")

    # --- 1. データの読み込み ---
    # Streamlitのキャッシュ機能を使って接続
    spreadsheet_url = "https://docs.google.com/spreadsheets/d/1WdRMiZ8RMrLHo5yFrVCSYrDlyC6IGWhvY9fcZiE9rQ0/edit"

    # 1. 接続はシンプルに作る（ここではURLを渡さない！）
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 2. 読むときに「このURLを読んでね」と指定する
    df_config = conn.read(spreadsheet=spreadsheet_url, worksheet="Config", ttl=0)
    df_responses = conn.read(spreadsheet=spreadsheet_url, worksheet="Responses", ttl=0)

    # --- 2. データの整形 ---
    # データフレームから辞書やリストへ変換して使いやすくする
    users = df_config[df_config['type'] == 'user'].set_index('id')['name'].to_dict()
    slots = df_config[df_config['type'] == 'slot'][['id', 'name']].to_dict('records')
    groups_raw = df_config[df_config['type'] == 'group'].to_dict('records')
    
    # グループ情報の構築
    groups = {}
    for g in groups_raw:
        member_ids = str(g['extra']).split(',') if pd.notna(g['extra']) else []
        member_ids = [m.strip() for m in member_ids] # 空白除去
        groups[g['id']] = {"name": g['name'], "members": member_ids}

    # 回答データの辞書化 {(user_id, slot_id): status}
    response_map = {}
    for _, row in df_responses.iterrows():
        response_map[(row['user_id'], row['slot_id'])] = row['status']

    # --- 3. UI構築 ---
    
    # ユーザー切り替え（簡易ログイン）
    st.sidebar.header("ログイン")
    # 辞書のキー(id)と値(name)を使ってセレクトボックスを作る
    current_user_id = st.sidebar.selectbox(
        "あなたの名前を選んでください", 
        options=list(users.keys()), 
        format_func=lambda x: users[x]
    )
    
    st.sidebar.info("💡 管理者がスプレッドシートを更新すれば、メンバーや日程は自動で反映されます。")

    tab1, tab2 = st.tabs(["📝 予定を入力する", "📅 全員の予定を見る"])

    # === タブ1: 入力画面 ===
    with tab1:
        st.subheader(f"{users[current_user_id]} さんの予定登録")
        with st.form("input_form"):
            new_responses = []
            
            for slot in slots:
                slot_id = slot['id']
                slot_label = slot['name']
                
                # 現在の回答を取得（なければ「？」）
                current_val = response_map.get((current_user_id, slot_id), "？")
                try:
                    idx = STATUS_OPTIONS.index(current_val)
                except ValueError:
                    idx = 2
                
                val = st.radio(
                    f"**{slot_label}**",
                    options=STATUS_OPTIONS,
                    index=idx,
                    horizontal=True,
                    key=f"radio_{slot_id}"
                )
                new_responses.append({"user_id": current_user_id, "slot_id": slot_id, "status": val})
            
            st.markdown("---")
            submitted = st.form_submit_button("保存する")
            
            if submitted:
                # 更新ロジック: 現在のdf_responsesから、今のユーザーの古いデータを消して新しいデータを追加
                # 1. 今のユーザー以外のデータを残す
                other_users_df = df_responses[df_responses['user_id'] != current_user_id]
                
                # 2. 新しいデータをDataFrame化
                new_df = pd.DataFrame(new_responses)
                
                # 3. 結合
                updated_df = pd.concat([other_users_df, new_df], ignore_index=True)
                
                # 4. スプレッドシートに書き込み
                conn.update(worksheet="Responses", data=updated_df)
                st.success("保存しました！タブを切り替えて結果を確認してください。")
                st.rerun() # 画面リロード

    # === タブ2: 確認画面 ===
    with tab2:
        st.subheader("グループ別スケジュール確認")
        
        selected_group_id = st.selectbox(
            "確認したいバンド", 
            options=list(groups.keys()),
            format_func=lambda x: groups[x]['name']
        )
        
        target_group = groups[selected_group_id]
        target_members = target_group['members'] # IDリスト
        
        # 表示用データ作成
        view_data = []
        for slot in slots:
            row = {"日程": slot['name']}
            all_ok = True
            has_ng = False
            
            for uid in target_members:
                # メンバーIDがConfigに存在するかチェック
                u_name = users.get(uid, uid)
                st_val = response_map.get((uid, slot['id']), "？")
                row[u_name] = st_val
                
                if st_val != "〇":
                    all_ok = False
                if st_val == "×":
                    has_ng = True
            
            if has_ng:
                row["判定"] = "❌"
            elif all_ok:
                row["判定"] = "🎯"
            else:
                row["判定"] = "⚠️"
                
            view_data.append(row)
            
        st.table(pd.DataFrame(view_data))

if __name__ == "__main__":
    main()