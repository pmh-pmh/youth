import streamlit as st
import pandas as pd
import os
import re
import numpy as np
import io

# ==================== 配置区 ====================

TEAM_KEYWORDS = ['团体']               # 团体项目
MIXED_KEYWORDS = ['混合接力']          # 混合接力
ALLROUND_KEYWORDS = ['全能']           # 全能

# ----- 项群精确映射 -----
GROUP_ITEMS = {
    '接力': {
        '男4×100米接力', '女4×100米接力',
        '男4×400米接力', '女4×400米接力',
        '混合4×100米混合接力'
    },
    '跨栏': {
        '男110米栏', '女100米栏',
        '男400米栏', '女400米栏'
    },
    '跳跃': {
        '男跳高', '男撑竿跳高',
        '男跳远', '男三级跳远'
    },
    '投掷': {
        '女铅球（旋转）', '女链球',
        '女铁饼', '女标枪'
    },
    '竞走': {
        '男5000米竞走', '女5000米竞走',
        '混合2×5000米竞走混合接力'
    }
}

# 成绩达标线
STANDARDS = {
    '男110米栏': 13.30,
    '女100米栏': 13.80,
    '男400米栏': 52.15,
    '女400米栏': 60.00,
    '男跳高': 2.10,
    '男撑竿跳高': 5.00,
    '男跳远': 7.30,
    '男三级跳远': 15.50,
    '女铅球（旋转）': 17.00,
    '女链球': 69.00,
    '女铁饼': 53.00,
    '女标枪': 57.00,
    '男5000米竞走': 21.00,
    '女5000米竞走': 23.20,
}

# ==================== 工具函数 ====================

def parse_time_to_seconds(time_val):
    if pd.isna(time_val):
        return np.nan
    if isinstance(time_val, (int, float)):
        return float(time_val)
    time_str = str(time_val).strip()
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    try:
        return float(time_str)
    except:
        return np.nan

def extract_core_event(full_name):
    pattern = r'^(男子|女子)(U\d+组)?(.*)$'
    match = re.match(pattern, full_name)
    if match:
        return match.group(3).strip()
    return full_name.strip()

def get_event_group(row):
    gender = row['性别']
    core = extract_core_event(row['项目'])
    if any(k in core for k in ['铅球', '链球', '铁饼', '标枪']):
        return '投掷'
    key = gender + core
    for group, items in GROUP_ITEMS.items():
        if group == '投掷':
            continue
        if key in items:
            return group
    return None

def check_standard(row):
    event = row['项目']
    gender = row['性别']
    score = row['成绩']
    core = extract_core_event(event)
    # 投掷
    if any(k in core for k in ['铅球', '链球', '铁饼', '标枪']):
        if '铅球' in core:
            std = STANDARDS.get('女铅球（旋转）')
        elif '链球' in core:
            std = STANDARDS.get('女链球')
        elif '铁饼' in core:
            std = STANDARDS.get('女铁饼')
        elif '标枪' in core:
            std = STANDARDS.get('女标枪')
        else:
            return True
        if std is None:
            return True
        try:
            val = float(score)
        except:
            return False
        return val >= std
    if '接力' in core:
        return True
    key = gender + core
    if key not in STANDARDS:
        return True
    std = STANDARDS[key]
    if isinstance(score, str) and ':' in score:
        seconds = parse_time_to_seconds(score)
        if pd.isna(seconds):
            return False
        if '竞走' in core:
            std_seconds = std * 60
            return seconds <= std_seconds
        else:
            return seconds <= std
    else:
        try:
            val = float(score)
        except:
            return False
        if any(k in core for k in ['栏', '竞走']):
            return val <= std
        else:
            return val >= std

# ==================== 团体总分计算（含并列、破纪录） ====================

def get_best_two_or_three_sum(group_df, event_name):
    province_scores = {}
    for province, prov_data in group_df.groupby('单位'):
        valid = prov_data[prov_data['成绩'].notna()]
        if valid.empty:
            continue
        valid = valid.copy()
        valid['成绩_数值'] = valid['成绩'].apply(parse_time_to_seconds)
        valid = valid.dropna(subset=['成绩_数值'])
        if valid.empty:
            continue
        if '竞走' in event_name and '团体' in event_name:
            top_n = valid.nsmallest(3, '成绩_数值')
            required = 3
        else:
            top_n = valid.nlargest(2, '成绩_数值')
            required = 2
        if len(top_n) < required:
            continue
        total = top_n['成绩_数值'].sum()
        province_scores[province] = total
    return province_scores

def process_team_events(df, gender):
    mask = (df['性别'] == gender) & (df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False))
    team_df = df[mask].copy()
    if team_df.empty:
        return pd.DataFrame(columns=['单位', '类别', '积分'])
    results = []
    for event_name, event_data in team_df.groupby('项目'):
        province_scores = get_best_two_or_three_sum(event_data, event_name)
        if not province_scores:
            continue
        if '竞走' in event_name:
            sorted_items = sorted(province_scores.items(), key=lambda x: x[1])
        else:
            sorted_items = sorted(province_scores.items(), key=lambda x: x[1], reverse=True)
        score_map = {1:9, 2:7, 3:6, 4:5, 5:4, 6:3, 7:2, 8:1}
        index = 0
        rank = 1
        while index < len(sorted_items) and rank <= 8:
            current_score = sorted_items[index][1]
            group = []
            while index < len(sorted_items) and sorted_items[index][1] == current_score:
                group.append(sorted_items[index])
                index += 1
            k = len(group)
            score_sum = 0
            for r in range(rank, min(rank + k, 9)):
                score_sum += score_map.get(r, 0)
            avg_base = score_sum / k
            final_base = avg_base * 2
            for province, _ in group:
                # ---------- 修改点：判断是否包含 MR ----------
                if '是否破纪录' in event_data.columns:
                    # 检查该单位在该项目中是否有任何一条记录包含 MR（不区分大小写）
                    record_mask = (event_data['单位'] == province) & (
                        event_data['是否破纪录'].astype(str).str.contains('MR', case=False, na=False)
                    )
                    record_broken = event_data[record_mask]
                else:
                    record_broken = pd.DataFrame()
                final_score = final_base + (5 if not record_broken.empty else 0)
                # ------------------------------------------
                if '竞走' in event_name:
                    category = '竞走团体'
                elif '跳远' in event_name:
                    category = '跳远团体'
                elif '铅球' in event_name:
                    category = '铅球团体'
                elif '铁饼' in event_name:
                    category = '铁饼团体'
                elif '链球' in event_name:
                    category = '链球团体'
                elif '标枪' in event_name:
                    category = '标枪团体'
                else:
                    category = '投掷团体'
                results.append({'单位': province, '类别': category, '积分': final_score})
            rank += k
    return pd.DataFrame(results)

def process_individual_and_relay(df, gender):
    mask = (df['性别'] == gender) & (~df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False)) & (~df['项目'].str.contains('|'.join(MIXED_KEYWORDS), na=False))
    filtered = df[mask].copy()
    if filtered.empty:
        return pd.DataFrame(columns=['单位', '类别', '积分'])
    results = []
    for _, row in filtered.iterrows():
        score = row['积分']
        if pd.isna(score) or score == 0:
            continue
        if any(kw in row['项目'] for kw in ALLROUND_KEYWORDS):
            category = '全能'
            final_score = score * 2
        else:
            category = '个人（接力）'
            final_score = score
        # ---------- 修改点：判断是否包含 MR ----------
        record_val = row.get('是否破纪录', '')
        if isinstance(record_val, str) and 'MR' in record_val.upper():
            final_score += 5
        # ------------------------------------------
        results.append({'单位': row['单位'], '类别': category, '积分': final_score})
    return pd.DataFrame(results)

def process_mixed_relay(df, gender):
    mask = (df['性别'] == gender) & (df['项目'].str.contains('|'.join(MIXED_KEYWORDS), na=False))
    mixed = df[mask].copy()
    if mixed.empty:
        return pd.DataFrame(columns=['单位', '类别', '积分'])
    results = []
    for _, row in mixed.iterrows():
        score = row['积分']
        if pd.isna(score) or score == 0:
            continue
        final_score = score
        # ---------- 修改点：判断是否包含 MR ----------
        record_val = row.get('是否破纪录', '')
        if isinstance(record_val, str) and 'MR' in record_val.upper():
            final_score += 2.5
        # ------------------------------------------
        results.append({'单位': row['单位'], '类别': '混合接力', '积分': final_score})
    return pd.DataFrame(results)

def generate_team_report(df):
    mixed_mask = df['项目'].str.contains('|'.join(MIXED_KEYWORDS), na=False)
    mixed_rows = []
    for _, row in df[mixed_mask].iterrows():
        men_row = row.copy()
        men_row['性别'] = '男'
        men_row['积分'] = row['积分'] * 0.5 if not pd.isna(row['积分']) else 0
        mixed_rows.append(men_row)
        women_row = row.copy()
        women_row['性别'] = '女'
        women_row['积分'] = row['积分'] * 0.5 if not pd.isna(row['积分']) else 0
        mixed_rows.append(women_row)
    df_mixed = pd.DataFrame(mixed_rows)
    df_clean = df[~mixed_mask].copy()
    df_all = pd.concat([df_clean, df_mixed], ignore_index=True)
    
    reports = {}
    men_cols = ['个人（接力）', '全能', '竞走团体', '跳远团体', '混合接力']
    women_cols = ['个人（接力）', '全能', '竞走团体', '铅球团体', '铁饼团体', '链球团体', '标枪团体', '混合接力']
    
    for gender in ['男', '女']:
        team_df = process_team_events(df_all, gender)
        indiv_df = process_individual_and_relay(df_all, gender)
        mixed_df = process_mixed_relay(df_all, gender)
        combined = pd.concat([team_df, indiv_df, mixed_df], ignore_index=True)
        if combined.empty:
            continue
        pivot = combined.pivot_table(index='单位', columns='类别', values='积分', aggfunc='sum', fill_value=0).reset_index()
        if gender == '男':
            expected_cols = men_cols
        else:
            expected_cols = women_cols
        for col in expected_cols:
            if col not in pivot.columns:
                pivot[col] = 0
        pivot = pivot[['单位'] + expected_cols]
        pivot['总分'] = pivot[expected_cols].sum(axis=1)
        pivot = pivot.sort_values('总分', ascending=False).reset_index(drop=True)
        pivot.insert(0, '排名', range(1, len(pivot) + 1))
        reports[gender] = pivot
    return reports

# ==================== 项群明细 ====================

def generate_group_details(df):
    mask = (~df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False)) & \
           (~df['项目'].str.contains('|'.join(ALLROUND_KEYWORDS), na=False)) & \
           (df['积分'] > 0) & (df['积分'].notna())
    filtered = df[mask].copy()
    if filtered.empty:
        return {}
    filtered['项群'] = filtered.apply(get_event_group, axis=1)
    filtered = filtered[filtered['项群'].notna()]
    if filtered.empty:
        return {}
    filtered['达标'] = filtered.apply(check_standard, axis=1)
    filtered = filtered[filtered['达标'] == True]
    if filtered.empty:
        return {}
    filtered['小项'] = filtered.apply(lambda row: row['性别'] + extract_core_event(row['项目']), axis=1)
    result = {}
    for group_name in GROUP_ITEMS.keys():
        group_data = filtered[filtered['项群'] == group_name].copy()
        if group_data.empty:
            continue
        pivot = group_data.pivot_table(index='单位', columns='小项', values='积分', aggfunc='sum', fill_value=0).reset_index()
        expected_items = list(GROUP_ITEMS[group_name])
        for item in expected_items:
            if item not in pivot.columns:
                pivot[item] = 0
        pivot['项群合计'] = pivot[expected_items].sum(axis=1)
        pivot = pivot.sort_values('项群合计', ascending=False).reset_index(drop=True)
        pivot.insert(0, '排名', range(1, len(pivot) + 1))
        pivot = pivot[pivot['排名'] <= 8]
        cols = ['排名', '单位', '项群合计'] + expected_items
        pivot = pivot[cols]
        result[group_name] = pivot
    return result

# ==================== 奖牌榜统计（按项目类别） ====================

def generate_medal_by_category(df):
    """
    返回一个字典，键为 '个人'、'接力'、'团体'，值为DataFrame（排名, 单位, 金牌, 银牌, 铜牌, 总数）
    """
    medal_records = []  # (单位, 名次, 类别)

    # 1. 个人项目（不含接力、团体）
    individual_mask = (~df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False)) & \
                      (~df['项目'].str.contains('|'.join(MIXED_KEYWORDS), na=False))
    indiv_df = df[individual_mask].copy()
    if '名次' in indiv_df.columns:
        indiv_df = indiv_df[indiv_df['名次'].isin([1,2,3])]
        for _, row in indiv_df.iterrows():
            medal_records.append({
                '单位': row['单位'],
                '名次': int(row['名次']),
                '类别': '个人'
            })

    # 2. 接力项目（包含“接力”关键词，包括混合接力）
    relay_mask = df['项目'].str.contains('接力', na=False)
    relay_df = df[relay_mask].copy()
    if '名次' in relay_df.columns:
        relay_df = relay_df[relay_df['名次'].isin([1,2,3])]
        for _, row in relay_df.iterrows():
            medal_records.append({
                '单位': row['单位'],
                '名次': int(row['名次']),
                '类别': '接力'
            })

    # 3. 团体项目（包含“团体”关键词）
    team_mask = df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False)
    team_df = df[team_mask].copy()
    if not team_df.empty:
        # 按性别、项目分组计算名次（与团体总分逻辑一致）
        for gender in team_df['性别'].unique():
            for event_name in team_df[team_df['性别'] == gender]['项目'].unique():
                event_data = team_df[(team_df['性别'] == gender) & (team_df['项目'] == event_name)]
                province_scores = get_best_two_or_three_sum(event_data, event_name)
                if not province_scores:
                    continue
                if '竞走' in event_name:
                    sorted_items = sorted(province_scores.items(), key=lambda x: x[1])
                else:
                    sorted_items = sorted(province_scores.items(), key=lambda x: x[1], reverse=True)
                for rank, (province, _) in enumerate(sorted_items, start=1):
                    if rank > 3:
                        break
                    medal_records.append({
                        '单位': province,
                        '名次': rank,
                        '类别': '团体'
                    })

    if not medal_records:
        return {}

    medal_df = pd.DataFrame(medal_records)
    # 按类别分组生成透视表
    result = {}
    categories = ['个人', '接力', '团体']
    for cat in categories:
        sub = medal_df[medal_df['类别'] == cat]
        if sub.empty:
            continue
        pivot = sub.pivot_table(index='单位', columns='名次', aggfunc='size', fill_value=0).reset_index()
        for col in [1,2,3]:
            if col not in pivot.columns:
                pivot[col] = 0
        pivot.rename(columns={1:'金牌', 2:'银牌', 3:'铜牌'}, inplace=True)
        pivot['总数'] = pivot['金牌'] + pivot['银牌'] + pivot['铜牌']
        pivot = pivot.sort_values(['金牌', '银牌', '铜牌'], ascending=False).reset_index(drop=True)
        pivot.insert(0, '排名', range(1, len(pivot)+1))
        result[cat] = pivot

    # 总榜（所有类别合计）
    total_pivot = medal_df.pivot_table(index='单位', columns='名次', aggfunc='size', fill_value=0).reset_index()
    for col in [1,2,3]:
        if col not in total_pivot.columns:
            total_pivot[col] = 0
    total_pivot.rename(columns={1:'金牌', 2:'银牌', 3:'铜牌'}, inplace=True)
    total_pivot['总数'] = total_pivot['金牌'] + total_pivot['银牌'] + total_pivot['铜牌']
    total_pivot = total_pivot.sort_values(['金牌', '银牌', '铜牌'], ascending=False).reset_index(drop=True)
    total_pivot.insert(0, '排名', range(1, len(total_pivot)+1))
    result['总榜'] = total_pivot

    return result

# ==================== 辅助函数：生成居中对齐的列配置 ====================

def center_column_config(df):
    """为DataFrame的每一列生成居中对齐的Column配置"""
    return {col: st.column_config.Column(alignment="center") for col in df.columns}

# ==================== Streamlit 界面 ====================

st.set_page_config(page_title="青运会团体总分 & 项群明细 & 奖牌榜", layout="wide")
st.title("🏆 第二届青少年田径运动会 - 自动算分系统")
st.markdown("---")

excel_path = os.path.join(os.path.dirname(__file__), "自动算分.xlsx")
if not os.path.exists(excel_path):
    st.error(f"❌ 找不到文件：{excel_path}\n请确保 '自动算分.xlsx' 与程序在同一目录。")
    st.stop()

try:
    df = pd.read_excel(excel_path, dtype={'单位': str})
    st.success("✅ 数据加载成功！修改Excel并保存后，页面将自动刷新。")
except Exception as e:
    st.error(f"读取Excel失败：{e}")
    st.stop()

# 计算数据
reports = generate_team_report(df)
group_details = generate_group_details(df)
medal_data = generate_medal_by_category(df)

# ----- 奖牌榜（按类别）-----
st.header("🥇 奖牌榜")
if medal_data:
    # 总榜放在最前
    tabs = st.tabs(["🏅 总榜", "🏃 个人", "🏃‍♂️‍➡️ 接力", "👥 团体"])
    with tabs[0]:
        if '总榜' in medal_data:
            df_medal = medal_data['总榜']
            st.dataframe(df_medal, column_config=center_column_config(df_medal), width='stretch', height=400, hide_index=True)
        else:
            st.info("暂无总榜数据")
    with tabs[1]:
        if '个人' in medal_data:
            df_medal = medal_data['个人']
            st.dataframe(df_medal, column_config=center_column_config(df_medal), width='stretch', height=400, hide_index=True)
        else:
            st.info("暂无个人奖牌数据")
    with tabs[2]:
        if '接力' in medal_data:
            df_medal = medal_data['接力']
            st.dataframe(df_medal, column_config=center_column_config(df_medal), width='stretch', height=400, hide_index=True)
        else:
            st.info("暂无接力奖牌数据")
    with tabs[3]:
        if '团体' in medal_data:
            df_medal = medal_data['团体']
            st.dataframe(df_medal, column_config=center_column_config(df_medal), width='stretch', height=400, hide_index=True)
        else:
            st.info("暂无团体奖牌数据")
else:
    st.warning("未生成奖牌数据，请检查是否有名次列或奖牌记录。")
st.markdown("---")

# ----- 团体总分 -----
st.header("📊 团体总分")
col1, col2 = st.columns(2)
with col1:
    st.subheader("👨 男子团体")
    if '男' in reports:
        df_men = reports['男']
        st.dataframe(df_men, column_config=center_column_config(df_men), width='stretch', height=400, hide_index=True)
    else:
        st.info("暂无男子数据")
with col2:
    st.subheader("👩 女子团体")
    if '女' in reports:
        df_women = reports['女']
        st.dataframe(df_women, column_config=center_column_config(df_women), width='stretch', height=400, hide_index=True)
    else:
        st.info("暂无女子数据")
st.markdown("---")

# ----- 项群明细 -----
st.header("🏅 五个项群明细（前8名）")
if group_details:
    ordered_groups = ['接力', '跨栏', '跳跃', '投掷', '竞走']
    tabs = st.tabs(ordered_groups)
    for tab, group_name in zip(tabs, ordered_groups):
        with tab:
            if group_name in group_details:
                df_group = group_details[group_name]
                st.dataframe(df_group, column_config=center_column_config(df_group), width='stretch', height=350, hide_index=True)
            else:
                st.info(f"暂无 {group_name} 数据")
else:
    st.warning("未生成项群数据，请检查是否有符合项群计分规则的项目（前8名且达标）。")
st.markdown("---")

# ----- 导出按钮 -----
def export_all_data():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # 团体总分
        if '男' in reports:
            reports['男'].to_excel(writer, sheet_name='男子团体', index=False)
        if '女' in reports:
            reports['女'].to_excel(writer, sheet_name='女子团体', index=False)
        # 项群
        for group_name, df_group in group_details.items():
            sheet_name = group_name[:31]
            df_group.to_excel(writer, sheet_name=sheet_name, index=False)
        # 奖牌榜
        if medal_data:
            for category, df_medal in medal_data.items():
                sheet_name = category[:31]
                df_medal.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

st.download_button(
    label="📥 导出全部数据到 Excel",
    data=export_all_data(),
    file_name="青运会完整报表.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)

st.caption("💡 修改Excel并保存后，页面将自动刷新。")
st.caption("📌 破纪录加分：在Excel中新增'是否破纪录'列，填写 **MR**（不区分大小写，如 MR 或 MR (PB) 等，只要包含 MR 即可）系统自动加相应分数。")
st.caption("📌 竞走团体取前3名，其他团体取前2名，已按规程实现并列平均分。")
st.caption("📌 奖牌榜按项目类别（个人、接力、团体）分别统计金、银、铜牌数，混合接力归入接力类。")