import streamlit as st
import pandas as pd
import os
import re
import numpy as np
import io

# ==================== 配置区 ====================

TEAM_KEYWORDS = ['团体']               # 团体项目（用于团体总分处理）
ALLROUND_KEYWORDS = ['全能']           # 全能

# ----- 项群映射（接力、跨栏、竞走使用具体项目列表，跳跃和投掷单独处理） -----
GROUP_ITEMS = {
    '接力': {
        '4×100米接力', '4x100米接力', '4*100米接力',
        '4×400米接力', '4x400米接力', '4*400米接力'
    },
    '跨栏': {
        '110米栏', '100米栏',
        '400米栏'
    },
    '竞走': {
        '5000米竞走', '竞走接力'
    }
}
# 跳跃和投掷在 get_event_group 中单独处理

# 成绩达标线（竞走时间以分钟为单位）
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
    '女5000米竞走': 23.3333,
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
    pattern = r'^(男子|女子|混合)(U\d+组)?(.*)$'
    match = re.match(pattern, full_name)
    if match:
        return match.group(3).strip()
    return full_name.strip()

def get_event_group(row):
    gender = row['性别']
    core = extract_core_event(row['项目'])
    key = gender + core
    
    # 跳跃：只限男子
    if gender == '男':
        if any(k in core for k in ['跳高', '撑竿跳高', '撑杆跳高', '跳远', '三级跳远']):
            return '跳跃'
    
    # 投掷：只限女子，铅球必须含“旋转”
    if gender == '女':
        if '铅球' in core and '旋转' in core:
            return '投掷'
        if any(k in core for k in ['链球', '铁饼', '标枪']):
            return '投掷'
    
    # 接力、跨栏、竞走
    for group in ['接力', '跨栏', '竞走']:
        for item in GROUP_ITEMS[group]:
            if item in key:
                return group
    return None

def check_standard(row):
    event = row['项目']
    gender = row['性别']
    score = row['成绩']
    core = extract_core_event(event)
    
    # 投掷
    if gender == '女':
        if '铅球' in core and '旋转' in core:
            std = STANDARDS.get('女铅球（旋转）')
        elif '链球' in core:
            std = STANDARDS.get('女链球')
        elif '铁饼' in core:
            std = STANDARDS.get('女铁饼')
        elif '标枪' in core:
            std = STANDARDS.get('女标枪')
        else:
            std = None
        if std is not None:
            try:
                val = float(score)
                return val >= std
            except:
                return False
    
    if '接力' in core:
        return True
    
    key = gender + core
    if key not in STANDARDS:
        return True
    
    std = STANDARDS[key]
    if '竞走' in core:
        seconds = parse_time_to_seconds(score)
        if pd.isna(seconds):
            return False
        return seconds <= std * 60
    else:
        if isinstance(score, str) and ':' in score:
            seconds = parse_time_to_seconds(score)
            if pd.isna(seconds):
                return False
            return seconds <= std
        else:
            try:
                val = float(score)
            except:
                return False
            if any(k in core for k in ['栏']):
                return val <= std
            else:
                return val >= std

# ==================== 团体总分计算 ====================

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
        return pd.DataFrame(columns=['单位', '类别', '积分', '破纪录加分'])
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
                bonus = 0
                if '是否破纪录' in event_data.columns:
                    record_mask = (event_data['单位'] == province) & (
                        event_data['是否破纪录'].astype(str).str.contains('MR', case=False, na=False)
                    )
                    if not event_data[record_mask].empty:
                        bonus = 5
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
                results.append({
                    '单位': province,
                    '类别': category,
                    '积分': final_base,
                    '破纪录加分': bonus
                })
            rank += k
    return pd.DataFrame(results)

def process_individual_and_relay(df, gender):
    mask = (df['性别'] == gender) & (~df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False))
    filtered = df[mask].copy()
    if filtered.empty:
        return pd.DataFrame(columns=['单位', '类别', '积分', '破纪录加分'])
    
    bonus_used = set()
    results = []
    for _, row in filtered.iterrows():
        score = row['积分']
        if pd.isna(score):
            continue
        if any(kw in row['项目'] for kw in ALLROUND_KEYWORDS):
            category = '全能'
            base_score = score * 2
        else:
            category = '个人（接力）'
            base_score = score
        bonus = 0
        record_val = row.get('是否破纪录', '')
        if isinstance(record_val, str) and 'MR' in record_val.upper():
            name = row.get('姓名', '')
            if pd.isna(name) or str(name).strip() == '':
                key = (row['单位'], row['项目'])
            else:
                key = (row['单位'], row['项目'], str(name).strip())
            if key not in bonus_used:
                bonus = 5
                bonus_used.add(key)
        results.append({
            '单位': row['单位'],
            '类别': category,
            '积分': base_score,
            '破纪录加分': bonus
        })
    return pd.DataFrame(results)

def generate_team_report(df):
    # 混合项目（性别列='混合'）拆分
    mixed_mask = (df['性别'] == '混合')
    mixed_df = df[mixed_mask].copy()
    non_mixed_df = df[~mixed_mask].copy()

    mixed_results = []
    if not mixed_df.empty:
        for (unit, event), group in mixed_df.groupby(['单位', '项目']):
            score = group['积分'].sum()
            bonus = 0
            if '是否破纪录' in group.columns:
                if group['是否破纪录'].astype(str).str.contains('MR', case=False, na=False).any():
                    bonus = 5
            mixed_results.append({
                '单位': unit,
                '类别': '混合接力',
                '积分': score * 0.5,
                '破纪录加分': bonus * 0.5,
                '性别': '男'
            })
            mixed_results.append({
                '单位': unit,
                '类别': '混合接力',
                '积分': score * 0.5,
                '破纪录加分': bonus * 0.5,
                '性别': '女'
            })
    mixed_df_processed = pd.DataFrame(mixed_results) if mixed_results else pd.DataFrame(columns=['单位', '类别', '积分', '破纪录加分', '性别'])

    reports = {}
    men_cols = ['个人（接力）', '全能', '竞走团体', '跳远团体', '混合接力']
    women_cols = ['个人（接力）', '全能', '竞走团体', '铅球团体', '铁饼团体', '链球团体', '标枪团体', '混合接力']

    for gender in ['男', '女']:
        team_df = process_team_events(non_mixed_df, gender)
        indiv_df = process_individual_and_relay(non_mixed_df, gender)
        mixed_gender_df = mixed_df_processed[mixed_df_processed['性别'] == gender].drop(columns=['性别'])

        combined = pd.concat([team_df, indiv_df, mixed_gender_df], ignore_index=True)
        if combined.empty:
            continue

        pivot = combined.pivot_table(index='单位', columns='类别', values='积分', aggfunc='sum', fill_value=0).reset_index()
        bonus_total = combined.groupby('单位')['破纪录加分'].sum().reset_index()
        bonus_total.columns = ['单位', '破纪录加分']
        pivot = pivot.merge(bonus_total, on='单位', how='left').fillna({'破纪录加分': 0})

        if gender == '男':
            expected_cols = men_cols
        else:
            expected_cols = women_cols
        for col in expected_cols:
            if col not in pivot.columns:
                pivot[col] = 0

        pivot['总分'] = pivot[expected_cols].sum(axis=1) + pivot['破纪录加分']
        pivot = pivot.sort_values('总分', ascending=False).reset_index(drop=True)
        pivot.insert(0, '排名', range(1, len(pivot) + 1))
        final_cols = ['排名', '单位', '总分'] + expected_cols + ['破纪录加分']
        pivot = pivot[final_cols]
        reports[gender] = pivot

    return reports

# ==================== 项群明细 ====================

def generate_group_details(df):
    mask = (~df['项目'].str.contains('|'.join(TEAM_KEYWORDS), na=False)) & \
           (~df['项目'].str.contains('|'.join(ALLROUND_KEYWORDS), na=False)) & \
           (df['积分'] > 0) & (df['积分'].notna())
    
    if '赛次' in df.columns:
        df['赛次_clean'] = df['赛次'].astype(str).str.strip().str.lower()
        mask = mask & (df['赛次_clean'] == '决赛')
    
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
    ordered_groups = ['接力', '跨栏', '跳跃', '投掷', '竞走']
    for group_name in ordered_groups:
        group_data = filtered[filtered['项群'] == group_name].copy()
        if group_data.empty:
            continue
        pivot = group_data.pivot_table(index='单位', columns='小项', values='积分', aggfunc='sum', fill_value=0).reset_index()
        pivot['项群合计'] = pivot.drop(columns=['单位']).sum(axis=1)
        pivot = pivot.sort_values('项群合计', ascending=False).reset_index(drop=True)
        pivot.insert(0, '排名', range(1, len(pivot) + 1))
        pivot = pivot[pivot['排名'] <= 8]
        cols = ['排名', '单位', '项群合计'] + [c for c in pivot.columns if c not in ['排名', '单位', '项群合计']]
        pivot = pivot[cols]
        result[group_name] = pivot
    return result

# ==================== 奖牌榜统计（只统计总排名，过滤单人/个人记录） ====================

def generate_medal_by_category(df):
    # 过滤掉用于加分的“单人”/“个人”记录，只统计实际名次记录
    medal_df = df[~df['项目'].str.contains('单人|个人', na=False)].copy()
    medal_df = medal_df[medal_df['名次'].isin([1,2,3])]
    if medal_df.empty:
        return {}

    def classify(row):
        if row['性别'] == '混合':
            return '接力'
        if '团体' in row['项目']:
            return '团体'
        if '接力' in row['项目']:
            return '接力'
        return '个人'
    
    medal_df['类别'] = medal_df.apply(classify, axis=1)
    
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

# ==================== 辅助函数 ====================

def center_column_config(df):
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
    st.success("✅ 数据加载成功！")
except Exception as e:
    st.error(f"读取Excel失败：{e}")
    st.stop()

reports = generate_team_report(df)
group_details = generate_group_details(df)
medal_data = generate_medal_by_category(df)

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

st.header("🥇 奖牌榜")
if medal_data:
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

def export_all_data():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if '男' in reports:
            reports['男'].to_excel(writer, sheet_name='男子团体', index=False)
        if '女' in reports:
            reports['女'].to_excel(writer, sheet_name='女子团体', index=False)
        for group_name, df_group in group_details.items():
            sheet_name = group_name[:31]
            df_group.to_excel(writer, sheet_name=sheet_name, index=False)
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

st.caption("📌 奖牌榜只统计项目名不含'单人'/'个人'的记录（即总排名），算分使用所有记录。")
st.caption("📌 跳跃仅限男子，投掷仅限女子且铅球必须含'旋转'。")
st.caption("📌 混合项目（性别列='混合'）名次分和破纪录加分均男女各半。")
st.caption("📌 破纪录加分：同一运动员同一项目只计一次，不同运动员分别计。")
st.caption("📌 竞走团体取前3名，其他团体取前2名，并列按平均分处理。")