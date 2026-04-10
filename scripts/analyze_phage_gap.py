"""
分析 ClinicalTrials.gov 噬菌体试验数据差异
对比 API 返回结果与过滤后的结果
"""

import requests
import json
import time

API_BASE = "https://clinicaltrials.gov/api/v2/studies"

def fetch_raw_count(query_term):
    """获取原始查询结果数量（不过滤）"""
    url = f"{API_BASE}?query.term={query_term}&pageSize=100&format=json"
    all_ids = set()
    page_token = None
    page_count = 0
    
    for _ in range(20):  # 最多20页
        if page_token:
            url_with_token = f"{url}&pageToken={page_token}"
        else:
            url_with_token = url
            
        try:
            response = requests.get(url_with_token, timeout=30)
            if response.status_code != 200:
                print(f"[错误] HTTP {response.status_code}")
                break
                
            data = response.json()
            studies = data.get('studies', [])
            
            if not studies:
                break
                
            for study in studies:
                nct_id = study.get('protocolSection', {}).get('identificationModule', {}).get('nctId', '')
                if nct_id:
                    all_ids.add(nct_id)
            
            page_count += 1
            
            next_page_token = data.get('nextPageToken')
            if not next_page_token:
                break
            page_token = next_page_token
            time.sleep(0.3)
            
        except Exception as e:
            print(f"[错误] {e}")
            break
    
    return all_ids, page_count

def analyze_filtered_out(ids_before, ids_after):
    """分析被过滤掉的试验"""
    filtered_out = ids_before - ids_after
    return filtered_out

def get_study_details(nct_id):
    """获取单个试验详情"""
    url = f"{API_BASE}/{nct_id}"
    try:
        response = requests.get(url, params={'format': 'json'}, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[错误] 获取 {nct_id} 失败: {e}")
    return None

def main():
    print("="*70)
    print("ClinicalTrials.gov 噬菌体试验数据差异分析")
    print("="*70)
    
    # 1. 使用 bacteriophage 查询获取所有结果（不过滤）
    print("\n[1] 查询 'bacteriophage'（原始结果）...")
    raw_ids, raw_pages = fetch_raw_count("bacteriophage")
    print(f"   原始结果: {len(raw_ids)} 项 (共 {raw_pages} 页)")
    
    # 2. 模拟过滤逻辑
    print("\n[2] 应用过滤条件（标题/描述需包含 phage/bacteriophage）...")
    filtered_ids = set()
    filtered_out_details = []
    
    for nct_id in list(raw_ids)[:50]:  # 先检查前50个
        study = get_study_details(nct_id)
        if not study:
            continue
            
        protocol = study.get('protocolSection', {})
        title = (protocol.get('identificationModule', {}).get('briefTitle', '') or '').lower()
        description = (protocol.get('descriptionModule', {}).get('briefSummary', '') or '').lower()
        
        # 检查是否包含关键词
        if any(kw in title + description for kw in ['phage', 'bacteriophage', 'bacterio phage']):
            filtered_ids.add(nct_id)
        else:
            # 记录被过滤掉的试验
            conditions = protocol.get('conditionsModule', {}).get('conditions', [])
            interventions = protocol.get('armsInterventionsModule', {}).get('interventions', [])
            filtered_out_details.append({
                'nct_id': nct_id,
                'title': title[:100] + '...' if len(title) > 100 else title,
                'conditions': conditions[:3],
                'interventions': [i.get('name', '') for i in interventions[:3]]
            })
    
    print(f"   过滤后: {len(filtered_ids)} 项 (前50个样本)")
    print(f"   被过滤: {len(filtered_out_details)} 项")
    
    # 3. 显示被过滤的试验示例
    if filtered_out_details:
        print("\n[3] 被过滤掉的试验示例（前10个）:")
        for item in filtered_out_details[:10]:
            print(f"\n   - {item['nct_id']}")
            print(f"     标题: {item['title']}")
            print(f"     适应症: {', '.join(item['conditions']) if item['conditions'] else 'N/A'}")
            print(f"     干预措施: {', '.join(item['interventions']) if item['interventions'] else 'N/A'}")
    
    # 4. 分析原因
    print("\n[4] 差异原因分析:")
    print("   - ClinicalTrials.gov 'Other Terms' 搜索可能在以下字段中搜索:")
    print("     * 标题 (briefTitle)")
    print("     * 详细描述 (detailedDescription)")
    print("     * 条件/适应症 (conditions)")
    print("     * 干预措施 (interventions)")
    print("     * 其他术语 (otherTerms)")
    print("     * 关键词 (keywords)")
    print("   - 我们的过滤只检查标题和简要描述")
    print("   - 部分试验可能只在其他字段提到 bacteriophage")
    
    print("\n" + "="*70)

if __name__ == '__main__':
    main()
