"""
噬菌体临床试验数据采集模块 V2
改进点：
1. 扩大搜索范围 - 使用宽松关键词获取所有可能相关的研究
2. 审核状态跟踪 - 记录已审核的研究，避免重复处理
3. 增量采集 - 只处理新增研究
4. 人工审核辅助 - 提供 Study Overview 信息供判断
"""

import requests
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
PHAGE_DATA_FILE = DATA_DIR / 'phage_trials.json'
PHAGE_AUDIT_FILE = DATA_DIR / 'phage_audit_log.json'
PHAGE_CANDIDATES_FILE = DATA_DIR / 'phage_candidates.json'

# ClinicalTrials.gov API v2
API_BASE = "https://clinicaltrials.gov/api/v2/studies"

# 宽松的关键词搜索列表 - 尽可能捕获所有可能相关的研究
BROAD_QUERY_TERMS = [
    'bacteriophage',
    'phage therapy',
    'phage treatment',
    'phage cocktail',
    'phage preparation',
    'phage product',
    'phage lysate',
    'phage suspension',
    'bacteriophage therapy',
    'bacteriophage treatment',
    'bacteriophage cocktail',
    'bacteriophage preparation',
    'phage-antibiotic',
    'phage antibiotic synergy',
    'phage derived',
    'phage encoded',
    'endolysin',
    'depolymerase',
    'tailocin',
    'phage lysin',
]

# 审核状态常量
class AuditStatus:
    PENDING = 'pending'      # 待审核
    APPROVED = 'approved'    # 已审核 - 确认为噬菌体研究
    REJECTED = 'rejected'    # 已审核 - 非噬菌体研究
    UNCERTAIN = 'uncertain'  # 不确定，需要进一步判断


def load_audit_log() -> Dict[str, Any]:
    """加载审核记录"""
    if PHAGE_AUDIT_FILE.exists():
        try:
            with open(PHAGE_AUDIT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 审核记录加载失败: {e}")
    return {
        'audited_studies': {},  # nct_id -> {status, reason, audited_at}
        'last_search_time': None,
        'search_history': []
    }


def save_audit_log(audit_log: Dict):
    """保存审核记录"""
    PHAGE_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PHAGE_AUDIT_FILE, 'w', encoding='utf-8') as f:
        json.dump(audit_log, f, ensure_ascii=False, indent=2)


def get_study_details(nct_id: str) -> Optional[Dict]:
    """获取单个研究的完整详情（Study Overview）"""
    url = f"{API_BASE}/{nct_id}"
    try:
        response = requests.get(url, params={'format': 'json'}, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[错误] 获取 {nct_id} 详情失败: {e}")
    return None


def extract_study_overview(study_data: Dict) -> Dict:
    """从研究数据中提取关键的 Study Overview 信息，用于人工审核判断"""
    protocol = study_data.get('protocolSection', {})
    
    # 基本信息
    nct_id = protocol.get('identificationModule', {}).get('nctId', '')
    brief_title = protocol.get('identificationModule', {}).get('briefTitle', '')
    official_title = protocol.get('identificationModule', {}).get('officialTitle', '')
    
    # 描述信息
    description_module = protocol.get('descriptionModule', {})
    brief_summary = description_module.get('briefSummary', '')
    detailed_description = description_module.get('detailedDescription', '')
    
    # 干预措施
    interventions = []
    arms_interventions = protocol.get('armsInterventionsModule', {})
    for intervention in arms_interventions.get('interventions', []):
        interventions.append({
            'type': intervention.get('type', ''),
            'name': intervention.get('name', ''),
            'description': intervention.get('description', '')
        })
    
    # 适应症/条件
    conditions = protocol.get('conditionsModule', {}).get('conditions', [])
    
    # 关键词
    keywords = protocol.get('conditionsModule', {}).get('keywords', [])
    
    # 设计信息
    design = protocol.get('designModule', {})
    phases = design.get('phases', [])
    study_type = design.get('studyType', '')
    
    # 状态
    status = protocol.get('statusModule', {}).get('overallStatus', '')
    
    # 构建 Overview 摘要
    return {
        'nct_id': nct_id,
        'title': brief_title,
        'official_title': official_title,
        'brief_summary': brief_summary[:800] if brief_summary else '',
        'detailed_description': detailed_description[:1000] if detailed_description else '',
        'interventions': interventions,
        'conditions': conditions,
        'keywords': keywords,
        'phases': phases,
        'study_type': study_type,
        'status': status,
    }


def is_phage_related(overview: Dict) -> tuple:
    """
    自动判断研究是否与噬菌体相关
    返回: (is_related: bool, confidence: str, reasons: list)
    """
    text_to_check = ' '.join([
        overview.get('title', ''),
        overview.get('official_title', ''),
        overview.get('brief_summary', ''),
        overview.get('detailed_description', ''),
        ' '.join(overview.get('conditions', [])),
        ' '.join(overview.get('keywords', [])),
    ]).lower()
    
    # 干预措施文本
    for intervention in overview.get('interventions', []):
        text_to_check += ' ' + intervention.get('name', '').lower()
        text_to_check += ' ' + intervention.get('description', '').lower()
    
    # 强相关关键词（高置信度）
    strong_keywords = [
        'bacteriophage', 'phage therapy', 'phage treatment',
        'phage cocktail', 'phage preparation', 'phage product',
        'phage lysate', 'phage suspension', 'bacteriophage therapy',
        'bacteriophage treatment', 'bacteriophage cocktail',
    ]
    
    # 中等相关关键词
    medium_keywords = [
        'phage-antibiotic', 'phage antibiotic synergy', 'phage derived',
        'endolysin', 'depolymerase', 'tailocin', 'phage lysin',
        'phage encoded', 'phage engineering', 'engineered phage',
    ]
    
    # 弱相关但需人工确认
    weak_keywords = [
        'phage', 'phages', 'bacteriophages',
    ]
    
    reasons = []
    
    # 检查强相关关键词
    for kw in strong_keywords:
        if kw in text_to_check:
            reasons.append(f"包含强相关关键词: '{kw}'")
    
    if reasons:
        return True, 'high', reasons
    
    # 检查中等相关关键词
    for kw in medium_keywords:
        if kw in text_to_check:
            reasons.append(f"包含中等相关关键词: '{kw}'")
    
    if reasons:
        return True, 'medium', reasons
    
    # 检查弱相关关键词（需要人工确认）
    for kw in weak_keywords:
        if kw in text_to_check:
            reasons.append(f"包含弱相关关键词: '{kw}'，建议人工确认")
            return True, 'low', reasons
    
    return False, 'none', ['未检测到噬菌体相关关键词']


def search_all_candidates(max_pages: int = 20) -> Set[str]:
    """
    使用宽松的关键词搜索所有可能相关的研究
    返回候选研究的 NCT ID 集合
    """
    all_candidates = set()
    search_stats = {}
    
    print(f"\n{'='*70}")
    print("[阶段1] 广泛搜索候选研究")
    print(f"{'='*70}")
    print(f"使用 {len(BROAD_QUERY_TERMS)} 个关键词进行搜索...")
    
    for query_term in BROAD_QUERY_TERMS:
        candidates_from_term = set()
        page_token = None
        page_count = 0
        
        for page_num in range(max_pages):
            encoded_term = requests.utils.quote(query_term)
            url = f"{API_BASE}?query.term={encoded_term}&pageSize=100&format=json"
            
            if page_token:
                url += f"&pageToken={page_token}"
            
            try:
                response = requests.get(url, timeout=30)
                if response.status_code != 200:
                    print(f"  [警告] '{query_term}' 第 {page_num+1} 页请求失败: {response.status_code}")
                    break
                
                data = response.json()
                studies = data.get('studies', [])
                
                if not studies:
                    break
                
                for study in studies:
                    nct_id = study.get('protocolSection', {}).get('identificationModule', {}).get('nctId', '')
                    if nct_id:
                        candidates_from_term.add(nct_id)
                
                page_count += 1
                
                next_page_token = data.get('nextPageToken')
                if not next_page_token:
                    break
                page_token = next_page_token
                time.sleep(0.2)
                
            except Exception as e:
                print(f"  [错误] '{query_term}' 第 {page_num+1} 页: {e}")
                break
        
        search_stats[query_term] = {
            'candidates': len(candidates_from_term),
            'pages': page_count
        }
        all_candidates.update(candidates_from_term)
        print(f"  '{query_term}': {len(candidates_from_term)} 项 ({page_count} 页)")
        time.sleep(0.3)
    
    print(f"\n[汇总] 共发现 {len(all_candidates)} 个唯一候选研究")
    return all_candidates


def filter_new_candidates(candidate_ids: Set[str], audit_log: Dict) -> Set[str]:
    """
    过滤出需要处理的新候选研究
    排除已审核过的研究
    """
    audited_studies = audit_log.get('audited_studies', {})
    
    new_candidates = set()
    already_audited = set()
    
    for nct_id in candidate_ids:
        if nct_id in audited_studies:
            already_audited.add(nct_id)
        else:
            new_candidates.add(nct_id)
    
    print(f"\n{'='*70}")
    print("[阶段2] 候选研究去重")
    print(f"{'='*70}")
    print(f"  总候选研究: {len(candidate_ids)}")
    print(f"  已审核研究: {len(already_audited)}")
    print(f"  新增待审核: {len(new_candidates)}")
    
    return new_candidates


def audit_candidates(candidate_ids: Set[str], audit_log: Dict, auto_approve_high_confidence: bool = True) -> Dict:
    """
    审核候选研究
    返回审核结果: {approved: [], rejected: [], uncertain: []}
    """
    results = {
        'approved': [],
        'rejected': [],
        'uncertain': []
    }
    
    print(f"\n{'='*70}")
    print("[阶段3] 审核候选研究")
    print(f"{'='*70}")
    print(f"需要审核 {len(candidate_ids)} 个候选研究")
    print(f"高置信度自动通过: {'开启' if auto_approve_high_confidence else '关闭'}")
    print()
    
    candidate_list = sorted(list(candidate_ids))
    
    for i, nct_id in enumerate(candidate_list, 1):
        print(f"[{i}/{len(candidate_list)}] 审核 {nct_id}...", end=' ')
        
        # 获取研究详情
        study_data = get_study_details(nct_id)
        if not study_data:
            print("获取失败，跳过")
            continue
        
        # 提取 Overview
        overview = extract_study_overview(study_data)
        
        # 自动判断
        is_related, confidence, reasons = is_phage_related(overview)
        
        if is_related and confidence == 'high' and auto_approve_high_confidence:
            # 高置信度自动通过
            audit_record = {
                'nct_id': nct_id,
                'status': AuditStatus.APPROVED,
                'confidence': confidence,
                'reasons': reasons,
                'audited_at': datetime.now().isoformat(),
                'auto_approved': True,
                'title': overview['title']
            }
            audit_log['audited_studies'][nct_id] = audit_record
            results['approved'].append({
                'nct_id': nct_id,
                'overview': overview,
                'study_data': study_data
            })
            print("[OK] 自动通过 (高置信度)")
            
        elif is_related and confidence == 'medium' and auto_approve_high_confidence:
            # 中等置信度也自动通过，但标记
            audit_record = {
                'nct_id': nct_id,
                'status': AuditStatus.APPROVED,
                'confidence': confidence,
                'reasons': reasons,
                'audited_at': datetime.now().isoformat(),
                'auto_approved': True,
                'title': overview['title']
            }
            audit_log['audited_studies'][nct_id] = audit_record
            results['approved'].append({
                'nct_id': nct_id,
                'overview': overview,
                'study_data': study_data
            })
            print("[OK] 自动通过 (中等置信度)")
            
        elif is_related and confidence == 'low':
            # 低置信度，需要人工确认
            audit_record = {
                'nct_id': nct_id,
                'status': AuditStatus.PENDING,
                'confidence': confidence,
                'reasons': reasons,
                'audited_at': datetime.now().isoformat(),
                'auto_approved': False,
                'title': overview['title'],
                'overview': overview  # 保存完整信息供人工审核
            }
            audit_log['audited_studies'][nct_id] = audit_record
            results['uncertain'].append({
                'nct_id': nct_id,
                'overview': overview,
                'reasons': reasons
            })
            print("[?] 需人工确认 (低置信度)")
            
        else:
            # 不相关，自动拒绝
            audit_record = {
                'nct_id': nct_id,
                'status': AuditStatus.REJECTED,
                'confidence': confidence,
                'reasons': reasons,
                'audited_at': datetime.now().isoformat(),
                'auto_approved': True,
                'title': overview['title']
            }
            audit_log['audited_studies'][nct_id] = audit_record
            results['rejected'].append({
                'nct_id': nct_id,
                'overview': overview,
                'reasons': reasons
            })
            print("[NO] 自动拒绝")
        
        time.sleep(0.2)
    
    return results


def parse_trial_from_study(study_data: Dict) -> Dict:
    """将 Study Overview 解析为统一的 trial 格式"""
    protocol = study_data.get('protocolSection', {})
    
    nct_id = protocol.get('identificationModule', {}).get('nctId', '')
    title = protocol.get('identificationModule', {}).get('briefTitle', '')
    phases = protocol.get('designModule', {}).get('phases', [])
    overall_status = protocol.get('statusModule', {}).get('overallStatus', '')
    conditions = protocol.get('conditionsModule', {}).get('conditions', [])
    
    # 干预措施
    interventions = []
    interventions_data = protocol.get('armsInterventionsModule', {}).get('interventions', [])
    for inv in interventions_data:
        interventions.append({
            'type': inv.get('type', ''),
            'name': inv.get('name', ''),
            'description': inv.get('description', '')
        })
    
    # 给药途径
    route = extract_route(interventions_data)
    
    # 病原体
    pathogens = extract_pathogens(conditions, interventions)
    
    # 地点
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
        'locations': locations[:5],
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
        for phase in trial['phases']:
            if phase:
                stats['by_phase'][phase] = stats['by_phase'].get(phase, 0) + 1
        
        status = trial['status']
        if status:
            stats['by_status'][status] = stats['by_status'].get(status, 0) + 1
        
        for country in trial['countries']:
            if country:
                stats['by_country'][country] = stats['by_country'].get(country, 0) + 1
        
        for pathogen in trial['pathogens']:
            if pathogen:
                stats['by_pathogen'][pathogen] = stats['by_pathogen'].get(pathogen, 0) + 1
        
        for route in trial['route']:
            if route:
                stats['by_route'][route] = stats['by_route'].get(route, 0) + 1
        
        for cond in trial['conditions'][:2]:
            stats['by_condition'][cond] = stats['by_condition'].get(cond, 0) + 1
    
    stats['by_phase'] = dict(sorted(stats['by_phase'].items()))
    stats['by_status'] = dict(sorted(stats['by_status'].items(), key=lambda x: -x[1]))
    stats['by_country'] = dict(sorted(stats['by_country'].items(), key=lambda x: -x[1])[:15])
    stats['by_pathogen'] = dict(sorted(stats['by_pathogen'].items(), key=lambda x: -x[1]))
    stats['by_route'] = dict(sorted(stats['by_route'].items(), key=lambda x: -x[1]))
    stats['by_condition'] = dict(sorted(stats['by_condition'].items(), key=lambda x: -x[1])[:10])
    
    return stats


def save_candidates_for_manual_review(uncertain_candidates: List[Dict]):
    """保存需要人工确认的候选研究"""
    if not uncertain_candidates:
        return
    
    candidates_data = {
        'created_at': datetime.now().isoformat(),
        'count': len(uncertain_candidates),
        'candidates': [
            {
                'nct_id': c['nct_id'],
                'title': c['overview']['title'],
                'brief_summary': c['overview']['brief_summary'],
                'interventions': c['overview']['interventions'],
                'conditions': c['overview']['conditions'],
                'keywords': c['overview']['keywords'],
                'reasons': c['reasons']
            }
            for c in uncertain_candidates
        ]
    }
    
    with open(PHAGE_CANDIDATES_FILE, 'w', encoding='utf-8') as f:
        json.dump(candidates_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n[保存] {len(uncertain_candidates)} 个需人工确认的候选研究已保存至:")
    print(f"       {PHAGE_CANDIDATES_FILE}")


def run_collection_v2(auto_approve: bool = True):
    """
    执行改进的采集流程
    
    Args:
        auto_approve: 是否自动通过高置信度研究
    """
    print(f"\n{'='*70}")
    print(f"噬菌体临床试验采集 V2 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    
    # 1. 加载审核记录
    audit_log = load_audit_log()
    print(f"[加载] 已审核研究: {len(audit_log.get('audited_studies', {}))} 个")
    
    # 2. 广泛搜索候选研究
    all_candidates = search_all_candidates(max_pages=15)
    
    # 3. 过滤出新候选
    new_candidates = filter_new_candidates(all_candidates, audit_log)
    
    if not new_candidates:
        print(f"\n{'='*70}")
        print("[阶段3] 没有新的候选研究需要审核")
        print(f"{'='*70}")
        # 继续执行同步步骤，处理人工审核后批准的研究
    
    # 4. 审核新候选
    audit_results = audit_candidates(new_candidates, audit_log, auto_approve_high_confidence=auto_approve)
    
    # 5. 保存审核记录（如果有新候选）
    if new_candidates:
        audit_log['last_search_time'] = datetime.now().isoformat()
        audit_log['search_history'].append({
            'time': datetime.now().isoformat(),
            'total_candidates': len(all_candidates),
            'new_candidates': len(new_candidates),
            'approved': len(audit_results['approved']),
            'rejected': len(audit_results['rejected']),
            'uncertain': len(audit_results['uncertain'])
        })
        save_audit_log(audit_log)
        
        # 6. 保存需人工确认的候选
        if audit_results['uncertain']:
            save_candidates_for_manual_review(audit_results['uncertain'])
    
    # 7. 整合数据
    print(f"\n{'='*70}")
    print("[阶段4] 整合数据")
    print(f"{'='*70}")
    
    # 加载现有数据
    existing_trials = []
    if PHAGE_DATA_FILE.exists():
        try:
            with open(PHAGE_DATA_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                existing_trials = existing_data.get('trials', [])
        except Exception as e:
            print(f"[警告] 读取现有数据失败: {e}")
    
    print(f"  现有试验: {len(existing_trials)} 项")
    
    # 解析新批准的试验
    new_trials = []
    for approved in audit_results['approved']:
        trial = parse_trial_from_study(approved['study_data'])
        new_trials.append(trial)
    
    print(f"  新增试验: {len(new_trials)} 项")
    
    # 同步已批准但尚未纳入数据的研究（人工审核后批准的研究）
    existing_nct_ids = {t['nct_id'] for t in existing_trials}
    approved_nct_ids = {k for k, v in audit_log.get('audited_studies', {}).items() 
                        if v['status'] == AuditStatus.APPROVED}
    newly_approved_nct_ids = {a['nct_id'] for a in audit_results['approved']}
    missing_approved = approved_nct_ids - existing_nct_ids - newly_approved_nct_ids
    
    if missing_approved:
        print(f"  同步人工审核批准的研究: {len(missing_approved)} 项")
        for nct_id in missing_approved:
            study_data = get_study_details(nct_id)
            if study_data:
                trial = parse_trial_from_study(study_data)
                new_trials.append(trial)
                print(f"    + {nct_id}")
            time.sleep(0.2)
    
    # 合并数据（去重）
    seen_nct_ids = set()
    all_trials = []
    
    for trial in existing_trials + new_trials:
        nct_id = trial['nct_id']
        if nct_id not in seen_nct_ids:
            all_trials.append(trial)
            seen_nct_ids.add(nct_id)
    
    print(f"  合并后总数: {len(all_trials)} 项")
    
    # 8. 计算统计
    stats = calculate_stats(all_trials)
    
    # 9. 构建变化记录
    changes = []
    for approved in audit_results['approved']:
        changes.append({
            'type': 'new',
            'nct_id': approved['nct_id'],
            'title': approved['overview']['title'],
            'status': approved['overview']['status'],
            'phases': approved['overview']['phases'],
            'description': f"新增临床试验: {approved['overview']['title']}"
        })
    
    # 10. 保存数据
    data = {
        'trials': all_trials,
        'stats': stats,
        'changes': changes,
        'updated_at': datetime.now().isoformat(),
        'total_count': len(all_trials),
        'change_count': len(changes),
        'audit_info': {
            'version': 'v2',
            'auto_approved_count': len(audit_results['approved']),
            'manual_review_count': len(audit_results['uncertain']),
            'rejected_count': len(audit_results['rejected'])
        }
    }
    
    PHAGE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PHAGE_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 11. 输出汇总
    print(f"\n{'='*70}")
    print("[完成] 采集汇总")
    print(f"{'='*70}")
    print(f"  总试验数: {len(all_trials)}")
    print(f"  本次新增: {len(new_trials)}")
    print(f"  自动通过: {len(audit_results['approved'])}")
    print(f"  自动拒绝: {len(audit_results['rejected'])}")
    print(f"  需人工确认: {len(audit_results['uncertain'])}")
    print(f"\n  数据已保存至: {PHAGE_DATA_FILE}")
    print(f"  审核记录已保存至: {PHAGE_AUDIT_FILE}")
    
    if audit_results['uncertain']:
        print(f"\n  [!] 有 {len(audit_results['uncertain'])} 个研究需要人工确认")
        print(f"      请查看: {PHAGE_CANDIDATES_FILE}")
    
    return data


def manual_review(nct_id: str, approve: bool, reason: str = ''):
    """
    人工审核单个研究
    
    Args:
        nct_id: 研究的 NCT ID
        approve: 是否批准
        reason: 审核理由
    """
    audit_log = load_audit_log()
    
    if nct_id not in audit_log.get('audited_studies', {}):
        print(f"[错误] {nct_id} 不在待审核列表中")
        return False
    
    audit_record = audit_log['audited_studies'][nct_id]
    
    if audit_record['status'] != AuditStatus.PENDING:
        print(f"[警告] {nct_id} 已审核，当前状态: {audit_record['status']}")
        return False
    
    # 更新审核状态
    audit_record['status'] = AuditStatus.APPROVED if approve else AuditStatus.REJECTED
    audit_record['manual_review'] = True
    audit_record['review_reason'] = reason
    audit_record['reviewed_at'] = datetime.now().isoformat()
    
    save_audit_log(audit_log)
    
    action = "批准" if approve else "拒绝"
    print(f"[审核] {nct_id} 已{action}")
    print(f"       理由: {reason}")
    
    # 如果批准，需要重新运行采集以包含该研究
    if approve:
        print(f"\n[提示] 该研究已批准，请重新运行采集以包含此研究")
    
    return True


def show_audit_status():
    """显示当前审核状态"""
    audit_log = load_audit_log()
    audited = audit_log.get('audited_studies', {})
    
    approved = [k for k, v in audited.items() if v['status'] == AuditStatus.APPROVED]
    rejected = [k for k, v in audited.items() if v['status'] == AuditStatus.REJECTED]
    pending = [k for k, v in audited.items() if v['status'] == AuditStatus.PENDING]
    
    print(f"\n{'='*70}")
    print("审核状态统计")
    print(f"{'='*70}")
    print(f"  已批准: {len(approved)}")
    print(f"  已拒绝: {len(rejected)}")
    print(f"  待确认: {len(pending)}")
    print(f"  总计: {len(audited)}")
    
    if pending:
        print(f"\n待确认研究:")
        for nct_id in pending[:10]:
            record = audited[nct_id]
            print(f"  - {nct_id}: {record.get('title', 'N/A')[:60]}...")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'status':
            show_audit_status()
        elif command == 'review' and len(sys.argv) >= 4:
            nct_id = sys.argv[2]
            approve = sys.argv[3].lower() in ('yes', 'true', '1', 'approve')
            reason = sys.argv[4] if len(sys.argv) > 4 else ''
            manual_review(nct_id, approve, reason)
        else:
            print("用法:")
            print("  python phage_trials_v2.py           # 运行采集")
            print("  python phage_trials_v2.py status    # 查看审核状态")
            print("  python phage_trials_v2.py review <nct_id> <yes/no> [reason]")
    else:
        run_collection_v2(auto_approve=True)
