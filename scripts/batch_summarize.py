"""
BioKB 批量中文摘要生成
为所有缺少 chinese_summary 的文章生成中文摘要
"""

import sys
import os
import json
import re
import time
import sqlite3
import requests
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'biokb.db'
API_BASE = 'https://academicapi.com/v1'
API_KEY = 'sk-nzR1BI7nFGj42BCx6LJS4Pl5U4fYZuGyLNNf32PtnOs50Z10'


def generate_summary_batch(articles, batch_size=5):
    """批量生成中文摘要，每批处理多篇以节省 API 调用"""
    results = []
    total = len(articles)
    
    for i in range(0, total, batch_size):
        batch = articles[i:i+batch_size]
        
        # 构建批量 prompt
        articles_text = []
        for idx, a in enumerate(batch):
            articles_text.append(f"文章{idx+1}:\n标题: {a['title']}\n摘要: {a.get('summary', '无摘要')[:300]}")
        
        prompt = f"""请为以下{len(batch)}篇生物医药领域的文章各生成一段简洁的中文摘要（50-80字）。

要求：
1. 准确概括文章核心内容
2. 突出创新点和关键发现
3. 使用专业但易懂的中文
4. 每篇摘要独立一行

{"=".join(articles_text)}

请以JSON数组格式回复，每项包含 "index"（文章序号，从1开始）和 "chinese_summary"（中文摘要）。
只返回JSON，不要其他内容。"""

        try:
            resp = requests.post(
                f'{API_BASE}/chat/completions',
                headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
                json={
                    'model': 'deepseek-v3.2-exp-thinking',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.3,
                    'max_tokens': 1500,
                },
                timeout=60
            )
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                # Extract JSON from response
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    summaries = json.loads(json_match.group())
                    for s in summaries:
                        idx = s.get('index', 0) - 1
                        if 0 <= idx < len(batch):
                            results.append({
                                'id': batch[idx]['id'],
                                'chinese_summary': s.get('chinese_summary', '')
                            })
                    print(f"  [Batch {i//batch_size+1}] {len(summaries)} summaries generated")
                else:
                    # Fallback: try to parse individual lines
                    print(f"  [Batch {i//batch_size+1}] JSON parse failed, trying fallback")
                    for a in batch:
                        results.append(generate_single_summary(a))
            else:
                print(f"  [Batch {i//batch_size+1}] API error {resp.status_code}")
                for a in batch:
                    results.append(generate_single_summary(a))
        except Exception as e:
            print(f"  [Batch {i//batch_size+1}] Error: {e}")
            for a in batch:
                results.append({'id': a['id'], 'chinese_summary': ''})
        
        # Rate limiting
        time.sleep(1)
    
    return results


def generate_single_summary(article):
    """为单篇文章生成中文摘要"""
    prompt = f"""请为以下生物医药文章生成一段简洁的中文摘要（50-80字）：
标题: {article['title']}
摘要: {article.get('summary', '无摘要')[:300]}

只返回中文摘要文本，不要其他内容。"""
    try:
        resp = requests.post(
            f'{API_BASE}/chat/completions',
            headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-v3.2-exp-thinking',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 200,
            },
            timeout=30
        )
        if resp.status_code == 200:
            summary = resp.json()['choices'][0]['message']['content'].strip()
            return {'id': article['id'], 'chinese_summary': summary}
    except:
        pass
    return {'id': article['id'], 'chinese_summary': ''}


def main():
    if not DB_PATH.exists():
        print(f"[Error] Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get articles without chinese_summary
    c.execute('SELECT id, title, summary FROM articles WHERE chinese_summary IS NULL OR chinese_summary = ""')
    rows = c.fetchall()
    
    if not rows:
        print("[OK] All articles already have Chinese summaries!")
        conn.close()
        return
    
    print(f"[Summary] Found {len(rows)} articles without Chinese summary")
    print(f"[Summary] Processing in batches of 5...")
    
    articles = [dict(r) for r in rows]
    results = generate_summary_batch(articles, batch_size=5)
    
    # Update database
    updated = 0
    for r in results:
        if r.get('chinese_summary'):
            c.execute('UPDATE articles SET chinese_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                      (r['chinese_summary'], r['id']))
            updated += 1
    
    conn.commit()
    
    # Verify
    c.execute('SELECT COUNT(*) FROM articles WHERE chinese_summary IS NOT NULL AND chinese_summary != ""')
    done = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM articles')
    total = c.fetchone()[0]
    
    conn.close()
    print(f"\n[Summary] Done! Updated {updated}/{len(rows)} articles")
    print(f"[Summary] Total articles with Chinese summary: {done}/{total}")


if __name__ == '__main__':
    main()
