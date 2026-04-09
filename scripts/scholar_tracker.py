"""
BioKB 学者追踪模块
功能：
1. 从已采集文章中识别高影响力学者
2. 通过 Semantic Scholar API 追踪学者最新发表
3. 维护学者数据库和动态时间线
"""

import sys
import re
import json
import time
import sqlite3
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

DB_PATH = Path(__file__).parent.parent / 'data' / 'biokb.db'
SEMANTIC_API = 'https://api.semanticscholar.org/graph/v1'

# 预设高影响力学者（生物医药领域）
PRESET_SCHOLARS = [
    # 创新药领域
    {'name': 'Carl June', 'field': 'CAR-T, 免疫治疗', 'org': 'UPenn'},
    {'name': 'Michel Sadelain', 'field': 'CAR-T, 细胞治疗', 'org': 'MSKCC'},
    {'name': 'Jennifer Doudna', 'field': 'CRISPR, 基因编辑', 'org': 'UC Berkeley'},
    {'name': 'Emmanuelle Charpentier', 'field': 'CRISPR, 基因编辑', 'org': 'Max Planck'},
    {'name': 'David Liu', 'field': '碱基编辑, 基因治疗', 'org': 'Broad Institute'},
    {'name': 'Katalin Kariko', 'field': 'mRNA技术', 'org': 'UPenn / BioNTech'},
    {'name': 'Drew Weissman', 'field': 'mRNA疫苗', 'org': 'UPenn'},
    {'name': 'Ugur Sahin', 'field': 'mRNA, 癌症免疫', 'org': 'BioNTech'},
    {'name': 'Ozlem Tureci', 'field': 'mRNA, 癌症免疫', 'org': 'BioNTech'},
    {'name': 'Patrick Hsu', 'field': 'CRISPR, 基因编辑', 'org': 'Arc Institute'},
    # 生物制造领域
    {'name': 'Jay Keasling', 'field': '合成生物学, 生物制造', 'org': 'UC Berkeley'},
    {'name': 'Christopher Voigt', 'field': '合成生物学', 'org': 'MIT'},
    {'name': 'Pamela Silver', 'field': '合成生物学, 系统生物学', 'org': 'Harvard'},
    {'name': 'James Collins', 'field': '合成生物学, 抗菌', 'org': 'MIT'},
    {'name': 'Tom Ellis', 'field': '合成生物学, 酵母工程', 'org': 'Imperial College'},
    # 大健康/AI
    {'name': 'Eric Topol', 'field': '数字医疗, AI医学', 'org': 'Scripps Research'},
    {'name': 'Regina Barzilay', 'field': 'AI药物发现', 'org': 'MIT'},
    {'name': 'Daphne Koller', 'field': 'AI生物医学', 'org': 'Insitro'},
    {'name': 'Fei-Fei Li', 'field': 'AI医疗影像', 'org': 'Stanford'},
    # 中国学者
    {'name': 'Wei Wang', 'field': '结构生物学', 'org': 'Peking University'},
    {'name': 'Yigong Shi', 'field': '结构生物学', 'org': 'Westlake University'},
    {'name': 'Hui Cao', 'field': '化学遗传学, 药物设计', 'org': 'Peking University'},
    {'name': 'Xiaoliang Sunney Xie', 'field': '单分子生物物理', 'org': 'Peking University'},
    {'name': 'Jiankui He', 'field': '基因编辑', 'org': 'Shenzhen (former)'},  # Note: controversial
    {'name': 'Lu Chen', 'field': 'mRNA疫苗, 传染病', 'org': 'Fudan University'},
    {'name': 'Ning Li', 'field': '合成生物学', 'org': 'Tianjin University'},
]


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def search_semantic_scholar(name):
    """通过 Semantic Scholar API 搜索学者"""
    try:
        params = {'query': name, 'limit': 3, 'fields': 'name,authorId,affiliations,paperCount,hIndex,citationCount'}
        resp = requests.get(f'{SEMANTIC_API}/author/search', params=params, timeout=15,
                           headers={'User-Agent': 'BioKB/1.0'})
        if resp.status_code == 200:
            data = resp.json()
            authors = data.get('data', [])
            if authors:
                # Pick best match
                for a in authors:
                    a_name = a.get('name', '')
                    if name.lower() in a_name.lower() or a_name.lower() in name.lower():
                        return a
                return authors[0]
    except Exception as e:
        print(f"    [SemanticScholar] Search error for '{name}': {e}")
    return None


def get_scholar_recent_papers(author_id, days=30):
    """获取学者最近发表的论文"""
    try:
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        params = {
            'fields': 'title,abstract,authors,year,publicationDate,journal,externalIds,citationCount',
            'sort': 'publicationDate:desc',
            'limit': 20
        }
        resp = requests.get(f'{SEMANTIC_API}/author/{author_id}/papers', params=params, timeout=30,
                           headers={'User-Agent': 'BioKB/1.0'})
        if resp.status_code == 200:
            data = resp.json()
            papers = []
            for p in data.get('data', []):
                pub_date = p.get('publicationDate', '') or ''
                if not pub_date or pub_date < since:
                    continue
                doi = ''
                ext_ids = p.get('externalIds', {}) or {}
                if ext_ids:
                    doi = ext_ids.get('DOI', '')
                pmid = ext_ids.get('PubMed', '')
                
                authors = [a.get('name', '') for a in (p.get('authors', []) or [])]
                journal = ''
                j = p.get('journal', {}) or {}
                if j:
                    journal = j.get('name', '') or j.get('volume', '')
                
                papers.append({
                    'title': p.get('title', ''),
                    'summary': p.get('abstract', '')[:500] if p.get('abstract') else '',
                    'url': f'https://doi.org/{doi}' if doi else f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else '',
                    'source': 'SemanticScholar',
                    'authors': authors[:10],
                    'date': pub_date,
                    'journal': journal,
                    'category': 'scholar',
                    'scholar_name': '',
                    'doi': doi,
                    'citations': p.get('citationCount', 0),
                })
            return papers
    except Exception as e:
        print(f"    [SemanticScholar] Papers error: {e}")
    return []


def search_scholar_pubmed(name, field_hint='', days=60):
    """通过 PubMed 按作者名搜索最新论文"""
    try:
        import feedparser
        since = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
        # Try exact author search
        query = f'"{name}"[Author] AND ("{since}"[Date - Publication] : "3000"[Date - Publication])'
        
        base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils'
        params = {
            'db': 'pubmed',
            'term': query,
            'retmax': 10,
            'sort': 'date',
            'retmode': 'json'
        }
        resp = requests.get(f'{base}/esearch.fcgi', params=params, timeout=15)
        data = resp.json()
        ids = data.get('esearchresult', {}).get('idlist', [])
        
        if not ids:
            return []
        
        # Get summaries
        params2 = {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'json'}
        resp2 = requests.get(f'{base}/esummary.fcgi', params=params2, timeout=15)
        summaries = resp2.json().get('result', {})
        
        papers = []
        for pmid in ids:
            entry = summaries.get(pmid, {})
            title = entry.get('title', '').strip()
            if not title or len(title) < 15:
                continue
            
            summary = ''
            if 'abstract' in entry:
                abstract_texts = entry['abstract'].values() if isinstance(entry['abstract'], dict) else entry['abstract']
                if isinstance(abstract_texts, list):
                    summary = ' '.join(abstract_texts)
                else:
                    summary = str(abstract_texts)
                summary = re.sub(r'<[^>]+>', '', summary).strip()[:500]
            
            authors = [a.get('name', '') for a in entry.get('authors', [])]
            journal = entry.get('fulljournalname', '') or entry.get('source', '')
            
            date_str = ''
            date_parts = entry.get('pubdate', '')
            if date_parts:
                try:
                    date_str = datetime.strptime(date_parts.split()[0], '%Y/%m/%d').strftime('%Y-%m-%d')
                except:
                    try:
                        date_str = str(date_parts).split(' ')[0]
                    except:
                        pass
            
            papers.append({
                'title': title,
                'summary': summary,
                'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                'source': 'PubMed',
                'authors': authors[:10],
                'date': date_str,
                'journal': journal,
                'category': 'scholar',
                'scholar_name': name,
            })
        
        return papers
    except Exception as e:
        print(f"    [PubMed] Author search error for '{name}': {e}")
        return []


def extract_scholars_from_articles():
    """从已有文章中提取出现频率高的学者"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT authors, COUNT(*) as cnt FROM articles WHERE authors IS NOT NULL GROUP BY authors ORDER BY cnt DESC LIMIT 50')
    rows = c.fetchall()
    conn.close()
    
    author_counter = Counter()
    for row in rows:
        try:
            authors = json.loads(row['authors'])
            if isinstance(authors, list):
                for a in authors:
                    if a and len(a) > 3:
                        author_counter[a] += 1
        except:
            pass
    
    return author_counter.most_common(30)


def init_scholars_db():
    """初始化学者数据库，预设高影响力学者"""
    conn = get_db()
    c = conn.cursor()
    
    # Check if already initialized
    c.execute('SELECT COUNT(*) FROM scholars')
    count = c.fetchone()[0]
    if count > 0:
        print(f"[Scholars] DB already has {count} scholars")
        conn.close()
        return
    
    print(f"[Scholars] Initializing with {len(PRESET_SCHOLARS)} preset scholars...")
    
    for s in PRESET_SCHOLARS:
        c.execute('''INSERT OR IGNORE INTO scholars (name, organization, field, notes)
                     VALUES (?, ?, ?, ?)''',
                  (s['name'], s['org'], s['field'],
                   f"Preset: {s['org']} - {s['field']}"))
    
    conn.commit()
    conn.close()
    print(f"[Scholars] Initialized {len(PRESET_SCHOLARS)} scholars")


def sync_scholars_with_api():
    """通过 Semantic Scholar API 补充学者信息"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT id, name FROM scholars WHERE google_scholar_id IS NULL')
    scholars = c.fetchall()
    
    print(f"[Scholars] Syncing {len(scholars)} scholars with Semantic Scholar...")
    
    updated = 0
    for s in scholars:
        sid = s['id']
        name = s['name']
        print(f"  Searching: {name}...")
        
        result = search_semantic_scholar(name)
        if result:
            ss_id = result.get('authorId', '')
            affiliations = result.get('affiliations', []) or []
            org = ', '.join(affiliations) if affiliations else ''
            paper_count = result.get('paperCount', 0)
            h_index = result.get('hIndex', 0)
            citations = result.get('citationCount', 0)
            
            c.execute('''UPDATE scholars SET 
                          google_scholar_id = ?,
                          organization = COALESCE(NULLIF(?, ''), organization),
                          notes = ?,
                          last_check = CURRENT_TIMESTAMP
                         WHERE id = ?''',
                      (ss_id, org,
                       f"h-index={h_index}, papers={paper_count}, citations={citations}",
                       sid))
            updated += 1
            print(f"    Found: h-index={h_index}, papers={paper_count}")
        else:
            c.execute('UPDATE scholars SET last_check = CURRENT_TIMESTAMP WHERE id = ?', (sid,))
        
        time.sleep(1)  # Rate limiting
    
    conn.commit()
    conn.close()
    print(f"[Scholars] Synced {updated}/{len(scholars)} scholars")
    return updated


def collect_scholar_updates(days=60):
    """采集学者最新动态（论文）- 优先 PubMed 作者搜索，补充 Semantic Scholar"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT id, name, google_scholar_id, field FROM scholars')
    scholars = c.fetchall()
    
    if not scholars:
        print("[Scholars] No scholars found. Run init first.")
        conn.close()
        return []
    
    print(f"[Scholars] Collecting recent papers from {len(scholars)} scholars (last {days} days)...")
    
    all_papers = []
    new_count = 0
    
    for s in scholars:
        name = s['name']
        ss_id = s['google_scholar_id']
        
        papers = []
        
        # Method 1: PubMed author search (more reliable for academic papers)
        pubmed_papers = search_scholar_pubmed(name, s['field'] or '', days=days)
        papers.extend(pubmed_papers)
        if pubmed_papers:
            print(f"  {name}: PubMed found {len(pubmed_papers)} papers")
        
        # Method 2: Semantic Scholar (if we have ID)
        if ss_id and len(papers) < 3:
            ss_papers = get_scholar_recent_papers(ss_id, days=days)
            for p in ss_papers:
                p['scholar_name'] = name
                # Dedup by title
                if not any(p2['title'] == p['title'] for p2 in papers):
                    papers.extend([p])
            if ss_papers:
                print(f"  {name}: SemanticScholar found {len(ss_papers)} papers")
        
        for p in papers:
            p['scholar_name'] = name
            
            # Check duplicate
            import hashlib
            content_hash = hashlib.md5(f"{p['title']}|{p['source']}|scholar".encode()).hexdigest()
            c.execute('SELECT id FROM articles WHERE content_hash = ?', (content_hash,))
            if c.fetchone():
                continue
            
            # Insert
            try:
                c.execute('''INSERT INTO articles (title, summary, url, source, category,
                              journal, authors, publish_date, tags, content_hash)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (p['title'], p['summary'], p['url'], p['source'], p['category'],
                           p['journal'], json.dumps(p['authors'], ensure_ascii=False),
                           p['date'], json.dumps([name, 'scholar-update'], ensure_ascii=False),
                           content_hash))
                new_count += 1
            except sqlite3.IntegrityError:
                pass
        
        if papers:
            all_papers.extend(papers)
        
        time.sleep(0.4)  # Rate limiting
    
    conn.commit()
    conn.close()
    print(f"[Scholars] Total: {len(all_papers)} papers found, {new_count} new articles saved")
    return all_papers


def run_scholar_tracking():
    """执行完整的学者追踪流程"""
    print(f"\n{'='*60}")
    print(f"[Scholars] Tracking - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    # 1. Init
    init_scholars_db()
    
    # 2. Sync with API
    sync_scholars_with_api()
    
    # 3. Collect updates
    papers = collect_scholar_updates(days=60)
    
    # 4. Generate Chinese summaries for new scholar papers
    if papers:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, title, summary FROM articles WHERE category = "scholar" AND (chinese_summary IS NULL OR chinese_summary = "")')
        new_rows = [dict(r) for r in c.fetchall()]
        conn.close()
        
        if new_rows:
            print(f"[Scholars] Generating summaries for {len(new_rows)} new scholar articles...")
            sys.path.insert(0, str(Path(__file__).parent))
            try:
                from batch_summarize import generate_summary_batch
                results = generate_summary_batch(new_rows, batch_size=5)
                conn = get_db()
                c = conn.cursor()
                for r in results:
                    if r.get('chinese_summary'):
                        c.execute('UPDATE articles SET chinese_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                                  (r['chinese_summary'], r['id']))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"[Scholars] Summary generation failed: {e}")
    
    print(f"\n[Scholars] Tracking complete!")
    return papers


if __name__ == '__main__':
    run_scholar_tracking()
