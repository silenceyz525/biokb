"""
BioKB 数据采集增强模块
补充更多数据源：PubMed E-utilities、行业网站爬虫
"""

import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests', '-q'])
    import requests

try:
    import feedparser
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'feedparser', '-q'])
    import feedparser


def fetch_pubmed_abstracts(pmids):
    """通过 efetch 获取 PubMed 摘要（XML格式）"""
    abstracts = {}
    if not pmids:
        return abstracts
    try:
        base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils'
        for i in range(0, len(pmids), 10):
            batch = pmids[i:i+10]
            fetch_url = f"{base}/efetch.fcgi"
            params = {
                'db': 'pubmed',
                'id': ','.join(batch),
                'retmode': 'xml'
            }
            resp = requests.get(fetch_url, params=params, timeout=30)
            xml_text = resp.text
            # 分割每个 PubmedArticle
            articles = re.findall(r'<PubmedArticle>.*?</PubmedArticle>', xml_text, re.DOTALL)
            for article_xml in articles:
                pmid_match = re.search(r'<PMID[^>]*>(\d+)</PMID>', article_xml)
                if not pmid_match:
                    continue
                pmid = pmid_match.group(1)
                abs_matches = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', article_xml, re.DOTALL)
                if abs_matches:
                    full_abstract = ' '.join(re.sub(r'<[^>]+>', '', a) for a in abs_matches)
                    abstracts[pmid] = full_abstract.strip()
            time.sleep(0.5)
    except Exception as e:
        print(f"  [Abstracts] 获取失败: {e}")
    return abstracts


def fetch_pubmed_articles(query, max_results=25, retstart=0):
    """通过 PubMed E-utilities 采集论文（含英文摘要）"""
    articles = []
    try:
        base = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils'
        search_url = f"{base}/esearch.fcgi"
        params = {
            'db': 'pubmed',
            'term': query,
            'retmax': max_results,
            'retstart': retstart,
            'sort': 'date',
            'retmode': 'json'
        }
        resp = requests.get(search_url, params=params, timeout=15)
        data = resp.json()
        ids = data.get('esearchresult', {}).get('idlist', [])
        if not ids:
            print(f"  [PubMed] 查询 '{query[:40]}...' 无结果")
            return []

        fetch_url = f"{base}/esummary.fcgi"
        params2 = {
            'db': 'pubmed',
            'id': ','.join(ids),
            'retmode': 'json'
        }
        resp2 = requests.get(fetch_url, params=params2, timeout=15)
        summaries = resp2.json().get('result', {})

        print(f"  [PubMed] 获取 {len(ids)} 篇文章摘要...")
        abstracts = fetch_pubmed_abstracts(ids)

        for pmid in ids:
            entry = summaries.get(pmid, {})
            title = entry.get('title', '').strip()
            if not title or len(title) < 15:
                continue

            raw_abstract = abstracts.get(pmid, '')
            summary = raw_abstract[:800] if raw_abstract else ''

            authors = [a.get('name', '') for a in entry.get('authors', [])]
            journal = entry.get('fulljournalname', '') or entry.get('source', '')
            date_parts = entry.get('pubdate', '')
            date_str = ''
            if date_parts:
                try:
                    date_str = datetime.strptime(date_parts.split()[0] if ' ' in str(date_parts) else str(date_parts), '%Y/%m/%d').strftime('%Y-%m-%d')
                except:
                    try:
                        date_str = str(date_parts).split(' ')[0]
                    except:
                        pass

            articles.append({
                'title': title,
                'summary': summary,
                'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                'source': 'PubMed',
                'authors': authors[:10],
                'date': date_str,
                'journal': journal,
            })
        print(f"  [PubMed] 查询 '{query[:40]}...': {len(articles)} 篇（含摘要）")
        time.sleep(0.4)
    except Exception as e:
        print(f"  [PubMed] 查询失败: {e}")
    return articles


def fetch_eurekalert():
    """从 EurekAlert! 采集最新生物医药新闻"""
    articles = []
    try:
        feed = feedparser.parse('https://www.eurekalert.org/rss/biology.xml')
        for entry in feed.entries[:15]:
            title = entry.get('title', '').strip()
            if not title:
                continue
            summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
            articles.append({
                'title': title,
                'summary': summary,
                'url': entry.get('link', ''),
                'source': 'EurekAlert',
                'category': 'innovation',
                'authors': [],
                'date': '',
                'journal': 'EurekAlert!',
            })
        print(f"  [EurekAlert]: {len(articles)} 篇")
    except Exception as e:
        print(f"  [EurekAlert] 失败: {e}")
    return articles


def fetch_genetic_engineering_news():
    """采集 Genetic Engineering & Biotechnology News"""
    articles = []
    try:
        feed = feedparser.parse('https://www.genengnews.com/feed/')
        for entry in feed.entries[:20]:
            title = entry.get('title', '').strip()
            if not title or len(title) < 10:
                continue
            summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
            date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            articles.append({
                'title': title,
                'summary': summary,
                'url': entry.get('link', ''),
                'source': 'GEN',
                'category': 'biomanufacturing',
                'authors': [],
                'date': date,
                'journal': 'GEN',
            })
        print(f"  [GEN]: {len(articles)} 篇")
    except Exception as e:
        print(f"  [GEN] 失败: {e}")
    return articles


def fetch_stat_news():
    """采集 STAT News（生物医药领域权威新闻）"""
    articles = []
    try:
        resp = requests.get('https://www.statnews.com/feed/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        feed = feedparser.parse(resp.text)
        for entry in feed.entries[:15]:
            title = entry.get('title', '').strip()
            if not title or len(title) < 10:
                continue
            summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
            date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            # Classify
            lower = (title + ' ' + summary).lower()
            if any(w in lower for w in ['drug', 'therapy', 'fda', 'clinical', 'trial', 'treatment']):
                cat = 'innovation'
            elif any(w in lower for w in ['biotech', 'manufacturing', 'gene editing', 'cell therapy']):
                cat = 'biomanufacturing'
            else:
                cat = 'health'
            articles.append({
                'title': title,
                'summary': summary,
                'url': entry.get('link', ''),
                'source': 'STAT',
                'category': cat,
                'authors': [],
                'date': date,
                'journal': 'STAT News',
            })
        print(f"  [STAT]: {len(articles)} 篇")
    except Exception as e:
        print(f"  [STAT] 失败: {e}")
    return articles


def fetch_fierce_biotech():
    """采集 Fierce Biotech"""
    articles = []
    try:
        feed = feedparser.parse('https://www.fiercebiotech.com/rss')
        for entry in feed.entries[:15]:
            title = entry.get('title', '').strip()
            if not title or len(title) < 10:
                continue
            summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
            date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            articles.append({
                'title': title,
                'summary': summary,
                'url': entry.get('link', ''),
                'source': 'FierceBiotech',
                'category': 'innovation',
                'authors': [],
                'date': date,
                'journal': 'Fierce Biotech',
            })
        print(f"  [FierceBiotech]: {len(articles)} 篇")
    except Exception as e:
        print(f"  [FierceBiotech] 失败: {e}")
    return articles


def fetch_cnki_alternatives():
    """采集国内生物医药新闻（替代直接爬取CNKI）"""
    articles = []
    sources = [
        {
            'name': '生物探索',
            'url': 'https://www.biodiscover.com/rss.xml',
            'category': 'innovation',
        },
        {
            'name': '医麦客',
            'url': 'https://www.emedlive.com/rss.xml',
            'category': 'innovation',
        },
    ]
    for src in sources:
        try:
            feed = feedparser.parse(src['url'])
            count = 0
            for entry in feed.entries[:10]:
                title = entry.get('title', '').strip()
                if not title or len(title) < 8:
                    continue
                summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
                date = ''
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                    except:
                        pass
                articles.append({
                    'title': title,
                    'summary': summary,
                    'url': entry.get('link', ''),
                    'source': src['name'],
                    'category': src['category'],
                    'authors': [],
                    'date': date,
                    'journal': src['name'],
                })
                count += 1
            print(f"  [{src['name']}]: {count} 篇")
        except Exception as e:
            print(f"  [{src['name']}] 失败: {e}")
    return articles


# PubMed 查询词组
PUBMED_QUERIES = {
    '创新药': '("drug discovery"[Title/Abstract] OR "novel drug"[Title/Abstract] OR "CAR-T"[Title/Abstract] OR "gene therapy"[Title/Abstract] OR "antibody-drug conjugate"[Title/Abstract] OR "mRNA therapy"[Title/Abstract] OR "immunotherapy"[Title/Abstract] OR "ADC"[Title/Abstract]) AND "2026"[PDAT]',
    '生物制造': '("biomanufacturing"[Title/Abstract] OR "synthetic biology"[Title/Abstract] OR "bioprocessing"[Title/Abstract] OR "cell therapy manufacturing"[Title/Abstract] OR "CDMO"[Title/Abstract] OR "bioreactor"[Title/Abstract]) AND "2026"[PDAT]',
    '大健康': '("precision medicine"[Title/Abstract] OR "digital health"[Title/Abstract] OR "AI in healthcare"[Title/Abstract] OR "longevity"[Title/Abstract] OR "population health"[Title/Abstract]) AND "2026"[PDAT]',
    '噬菌体': '("bacteriophage"[Title/Abstract] OR "phage therapy"[Title/Abstract] OR "phage engineering"[Title/Abstract] OR "phage-antibiotic synergy"[Title/Abstract] OR "phage cocktail"[Title/Abstract] OR "phage display"[Title/Abstract] OR "lytic phage"[Title/Abstract] OR "temperate phage"[Title/Abstract] OR "phage resistance"[Title/Abstract] OR "antimicrobial phage"[Title/Abstract]) AND ("2025"[PDAT] OR "2026"[PDAT])',
}

CATEGORY_MAP = {
    '创新药': 'innovation',
    '生物制造': 'biomanufacturing',
    '大健康': 'health',
    '噬菌体': 'phage',
}


def fetch_phage_rss():
    """采集噬菌体专项 RSS 源"""
    articles = []
    phage_sources = [
        {
            'name': 'PubMed-噬菌体治疗',
            'url': 'https://pubmed.ncbi.nlm.nih.gov/rss/search/1VWpbTFQh6BKZJOH/?limit=20&utm_campaign=pubmed-2&fc=20250101170050',
            'fallback_url': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=(bacteriophage+OR+phage+therapy+OR+phage+engineering)&retmax=20&sort=date&rettype=rss',
        },
        {
            'name': 'Phage Biology Journal',
            'url': 'https://journals.asm.org/action/showFeed?type=etoc&feed=rss&jc=jvi',
        },
        {
            'name': 'bioRxiv-噬菌体',
            'url': 'http://connect.biorxiv.org/biorxiv_xml.php?subject=microbiology',
        },
    ]
    for src in phage_sources:
        try:
            url = src.get('url') or src.get('fallback_url')
            if not url:
                continue
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries[:20]:
                title = entry.get('title', '').strip()
                if not title or len(title) < 10:
                    continue
                lower_title = title.lower()
                if src['name'] in ('Phage Biology Journal', 'bioRxiv-噬菌体'):
                    phage_keywords = ['phage', 'bacteriophage', 'phage therapy', 'lytic', 'lysogenic',
                                      'virus-bacteria', 'virome', 'prophage', 'endolysin', 'tailocin']
                    if not any(kw in lower_title for kw in phage_keywords):
                        continue
                summary = re.sub(r'<[^>]+>', '', entry.get('summary', ''))[:500]
                date = ''
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                    except:
                        pass
                articles.append({
                    'title': title,
                    'summary': summary,
                    'url': entry.get('link', ''),
                    'source': src['name'],
                    'category': 'phage',
                    'authors': [],
                    'date': date,
                    'journal': src['name'],
                })
                count += 1
            print(f"  [{src['name']}]: {count} 篇")
        except Exception as e:
            print(f"  [{src['name']}] 失败: {e}")
    return articles


def run_enhanced_collection():
    """增强版全量采集"""
    print(f"\n{'='*60}")
    print(f"[enhanced] Start - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    all_articles = []

    # 1. PubMed papers（包含噬菌体专项）
    print("\n[PubMed] collecting papers:")
    for name, query in PUBMED_QUERIES.items():
        arts = fetch_pubmed_articles(query, max_results=25)
        for a in arts:
            a['category'] = CATEGORY_MAP.get(name, 'innovation')
        all_articles.extend(arts)

    # 2. Industry news RSS
    print("\n[News] collecting industry news:")
    all_articles.extend(fetch_eurekalert())
    all_articles.extend(fetch_genetic_engineering_news())
    all_articles.extend(fetch_fierce_biotech())
    try:
        all_articles.extend(fetch_stat_news())
    except:
        pass

    # 3. Chinese sources
    print("\n[CN] collecting Chinese sources:")
    all_articles.extend(fetch_cnki_alternatives())

    # 4. 噬菌体专项采集
    print("\n[Phage] collecting phage-specific sources:")
    all_articles.extend(fetch_phage_rss())

    print(f"\n[enhanced] Total collected: {len(all_articles)}")
    return all_articles


if __name__ == '__main__':
    articles = run_enhanced_collection()
    print(f"\n测试完成: {len(articles)} 篇")
