"""
噬菌体临床试验数据采集模块
从 ClinicalTrials.gov API 获取噬菌体疗法临床试验数据
"""

import requests
import json
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
PHAGE_DATA_FILE = DATA_DIR / 'phage_trials.json'

# ClinicalTrials.gov API v2
API_BASE = "https://clinicaltrials.gov/api/v2/studies"
QUERY = "bacteriophage%20OR%20phage%20therapy"


def fetch_all_trials(max_pages=15):
    """获取所有噬菌体相关临床试验"""
    all_trials = []
    seen_nct_ids = set()

    # 使用更全面的查询条件
    query_terms = [
        'bacteriophage',
        'phage therapy',
        'phage therapy bacteriophage',
        'antimicrobial phage',
    ]

    for query_term in query_terms:
        print(f"[查询] 搜索关键词: {query_term}")
        page_token = None
        page_count = 0

        for page_num in range(max_pages):
            # 构建查询 URL - 使用 query.term 参数
            encoded_term = query_term.replace(' ', '%20')
            url = f"{API_BASE}?query.term={encoded_term}&pageSize=100&format=json"

            if page_token:
                url += f"&pageToken={page_token}"

            try:
                response = requests.get(url, timeout=30)
                if response.status_code != 200:
                    print(f"[CT.gov API] 请求失败: {response.status_code}")
                    break

                data = response.json()
                studies = data.get('studies', [])

                if not studies:
                    break

                for study in studies:
                    trial = parse_trial(study)
                    if trial and trial['nct_id'] not in seen_nct_ids:
                        # 额外过滤：确保真的与噬菌体相关
                        title = (trial.get('title') or '').lower()
                        desc = (trial.get('description') or '').lower()
                        if any(kw in title + desc for kw in ['phage', 'bacteriophage', 'bacterio phage']):
                            all_trials.append(trial)
                            seen_nct_ids.add(trial['nct_id'])

                page_count += 1

                # 检查是否有下一页
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break

                page_token = next_page_token
                time.sleep(0.3)  # 避免请求过快

            except Exception as e:
                print(f"[CT.gov API] 第 {page_num + 1} 页获取失败: {e}")
                break

        print(f"[查询] {query_term}: 获取 {page_count} 页")
        time.sleep(0.5)

    print(f"[采集] 去重后共获取 {len(all_trials)} 条临床试验数据")
    return all_trials


def parse_trial(study):
    """解析单个临床试验数据"""
    protocol = study.get('protocolSection', {})

    # 基本信息
    nct_id = protocol.get('identificationModule', {}).get('nctId', '')
    title = protocol.get('identificationModule', {}).get('briefTitle', '')

    # 阶段
    phases = protocol.get('designModule', {}).get('phases', [])

    # 状态
    overall_status = protocol.get('statusModule', {}).get('overallStatus', '')

    # 适应症
    conditions = protocol.get('conditionsModule', {}).get('conditions', [])

    # 干预措施（提取病原体信息）
    interventions = []
    interventions_data = protocol.get('armsInterventionsModule', {}).get('interventions', [])
    for inv in interventions_data:
        inv_type = inv.get('type', '')
        inv_name = inv.get('name', '')
        inv_desc = inv.get('description', '')
        interventions.append({
            'type': inv_type,
            'name': inv_name,
            'description': inv_desc
        })

    # 给药途径
    route = extract_route(interventions_data)

    # 病原体
    pathogens = extract_pathogens(conditions, interventions)

    # 地点/国家
    locations = []
    locations_data = protocol.get('contactsLocationsModule', {}).get('locations', [])
    countries = set()
    for loc in locations_data:
        country = loc.get('country', '')
        city = loc.get('city', '')
        facility = loc.get('facility', '')
        if country:
            countries.add(country)
        locations.append({
            'country': country,
            'city': city,
            'facility': facility
        })

    # 描述
    description = protocol.get('descriptionModule', {}).get('briefSummary', '')

    # 招募人数
    enrollment = protocol.get('designModule', {}).get('enrollmentInfo', {}).get('count', '')

    # 更新时间
    last_update = protocol.get('statusModule', {}).get('lastUpdatePostDateStruct', {}).get('date', '')

    # 发起者
    sponsors = []
    sponsor_data = protocol.get('sponsorCollaboratorsModule', {}).get('leadSponsors', [])
    for sp in sponsor_data:
        sponsors.append({
            'name': sp.get('name', ''),
            'class': sp.get('class', '')
        })

    return {
        'nct_id': nct_id,
        'title': title,
        'phases': phases,
        'status': overall_status,
        'conditions': conditions,
        'interventions': interventions,
        'route': route,
        'pathogens': pathogens,
        'countries': list(countries),
        'locations': locations[:5],  # 只保留前5个地点
        'description': description[:500] if description else '',
        'enrollment': enrollment,
        'last_update': last_update,
        'sponsors': sponsors
    }


def extract_route(interventions):
    """从干预措施中提取给药途径"""
    routes = set()
    for inv in interventions:
        desc = inv.get('description', '').lower()
        name = inv.get('name', '').lower()

        if any(kw in desc or kw in name for kw in ['inhala', 'nebuliz', 'aerosol', '呼吸道', '吸入']):
            routes.add('雾化吸入')
        if any(kw in desc or kw in name for kw in ['intraven', 'IV', '静脉']):
            routes.add('静脉注射')
        if any(kw in desc or kw in name for kw in ['topical', '皮肤', '局部', '外用']):
            routes.add('局部外用')
        if any(kw in desc or kw in name for kw in ['oral', '口服', '吞咽']):
            routes.add('口服')
        if any(kw in desc or kw in name for kw in ['intraarticular', '关节', '关节腔']):
            routes.add('关节腔内注射')
        if any(kw in desc or kw in name for kw in ['bladder', '膀胱', '泌尿', 'urinary']):
            routes.add('膀胱灌注')

    return list(routes) if routes else ['其他']


def extract_pathogens(conditions, interventions):
    """从适应症和干预措施中提取病原体"""
    pathogens = set()
    all_text = ' '.join(conditions).lower() + ' ' + ' '.join([i.get('description', '') for i in interventions]).lower()

    pathogen_keywords = {
        '铜绿假单胞菌': ['pseudomonas aeruginosa', 'p. aeruginosa', 'paeruginosa'],
        '金黄色葡萄球菌': ['staphylococcus aureus', 's. aureus', 'saureus', 'mrsa'],
        '鲍曼不动杆菌': ['acinetobacter baumannii', 'a. baumannii', 'abaumannii'],
        '大肠杆菌': ['escherichia coli', 'e. coli', 'ecoli'],
        '肺炎克雷伯菌': ['klebsiella pneumoniae', 'k. pneumoniae', 'kpneumoniae'],
        '肠球菌': ['enterococcus', 'enterococci'],
        '脓肿分枝杆菌': ['mycobacterium abscessus', 'm. abscessus'],
        '分枝杆菌': ['mycobacterium', 'ntm'],
        '无色杆菌': ['achromobacter', 'a. xylosoxidans'],
        '伯克霍尔德菌': ['burkholderia', 'b. cepacia'],
        '沙门氏菌': ['salmonella'],
        '志贺氏菌': ['shigella'],
        '梭菌': ['clostridium', 'c. difficile', '艰难梭菌'],
    }

    for pathogen, keywords in pathogen_keywords.items():
        if any(kw in all_text for kw in keywords):
            pathogens.add(pathogen)

    return list(pathogens) if pathogens else []


def calculate_stats(trials):
    """计算统计数据"""
    stats = {
        'total': len(trials),
        'by_phase': {},
        'by_status': {},
        'by_country': {},
        'by_pathogen': {},
        'by_route': {},
        'by_condition': {}
    }

    for trial in trials:
        # 按阶段统计
        for phase in trial['phases']:
            if phase:
                stats['by_phase'][phase] = stats['by_phase'].get(phase, 0) + 1

        # 按状态统计
        status = trial['status']
        if status:
            stats['by_status'][status] = stats['by_status'].get(status, 0) + 1

        # 按国家统计
        for country in trial['countries']:
            if country:
                stats['by_country'][country] = stats['by_country'].get(country, 0) + 1

        # 按病原体统计
        for pathogen in trial['pathogens']:
            if pathogen:
                stats['by_pathogen'][pathogen] = stats['by_pathogen'].get(pathogen, 0) + 1

        # 按给药途径统计
        for route in trial['route']:
            if route:
                stats['by_route'][route] = stats['by_route'].get(route, 0) + 1

        # 按适应症统计（前10）
        for cond in trial['conditions'][:2]:  # 每条试验最多取2个适应症
            stats['by_condition'][cond] = stats['by_condition'].get(cond, 0) + 1

    # 排序
    stats['by_phase'] = dict(sorted(stats['by_phase'].items()))
    stats['by_status'] = dict(sorted(stats['by_status'].items(), key=lambda x: -x[1]))
    stats['by_country'] = dict(sorted(stats['by_country'].items(), key=lambda x: -x[1])[:15])
    stats['by_pathogen'] = dict(sorted(stats['by_pathogen'].items(), key=lambda x: -x[1]))
    stats['by_route'] = dict(sorted(stats['by_route'].items(), key=lambda x: -x[1]))
    stats['by_condition'] = dict(sorted(stats['by_condition'].items(), key=lambda x: -x[1])[:10])

    return stats


def detect_changes(new_trials, old_trials):
    """检测变化"""
    changes = []

    # 创建旧数据的索引
    old_by_nct = {t['nct_id']: t for t in old_trials}

    for new_trial in new_trials:
        nct_id = new_trial['nct_id']

        if nct_id not in old_by_nct:
            # 新增试验
            changes.append({
                'type': 'new',
                'nct_id': nct_id,
                'title': new_trial['title'],
                'status': new_trial['status'],
                'phases': new_trial['phases'],
                'pathogens': new_trial['pathogens'],
                'description': f"新增临床试验: {new_trial['title']}"
            })
        else:
            old_trial = old_by_nct[nct_id]
            # 检查状态变化
            if new_trial['status'] != old_trial['status']:
                changes.append({
                    'type': 'status_change',
                    'nct_id': nct_id,
                    'title': new_trial['title'],
                    'old_status': old_trial['status'],
                    'new_status': new_trial['status'],
                    'description': f"试验状态变更: {old_trial['status']} → {new_trial['status']}"
                })
            # 检查阶段变化
            if new_trial['phases'] != old_trial['phases']:
                changes.append({
                    'type': 'phase_change',
                    'nct_id': nct_id,
                    'title': new_trial['title'],
                    'old_phases': old_trial['phases'],
                    'new_phases': new_trial['phases'],
                    'description': f"试验阶段变更: {' / '.join(old_trial['phases'])} → {' / '.join(new_trial['phases'])}"
                })

    return changes


def run_collection():
    """执行采集流程"""
    print(f"\n{'='*60}")
    print(f"[噬菌体临床试验] 开始采集 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # 读取旧数据（用于变化检测）
    old_trials = []
    if PHAGE_DATA_FILE.exists():
        try:
            with open(PHAGE_DATA_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                old_trials = old_data.get('trials', [])
        except Exception as e:
            print(f"[读取] 旧数据读取失败: {e}")

    # 获取新数据
    new_trials = fetch_all_trials()

    if not new_trials:
        print("[采集] 未能获取数据，保持旧数据")
        return None

    # 检测变化
    changes = detect_changes(new_trials, old_trials)

    # 计算统计
    stats = calculate_stats(new_trials)

    # 构建完整数据
    data = {
        'trials': new_trials,
        'stats': stats,
        'changes': changes,
        'updated_at': datetime.now().isoformat(),
        'total_count': len(new_trials),
        'change_count': len(changes)
    }

    # 保存数据
    PHAGE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PHAGE_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[保存] 数据已保存至 {PHAGE_DATA_FILE}")
    print(f"[统计] 共 {stats['total']} 项试验")
    print(f"[变化] 检测到 {len(changes)} 项变化")

    if changes:
        print("\n变化详情:")
        for change in changes[:10]:  # 最多显示10条
            print(f"  - [{change['type']}] {change['nct_id']}: {change['description']}")

    return data


if __name__ == '__main__':
    run_collection()
