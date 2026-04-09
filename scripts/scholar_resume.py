"""
BioKB 学者履历生成器
使用 AI 为每位学者生成中文个人履历
"""

import sqlite3
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests', '-q'])
    import requests

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / 'data' / 'biokb.db'
API_BASE = 'https://academicapi.com/v1'
API_KEY = 'sk-nzR1BI7nFGj42BCx6LJS4Pl5U4fYZuGyLNNf32PtnOs50Z10'

# 学者额外信息（用于辅助 AI 生成更准确的履历）
SCHOLAR_HINTS = {
    'Carl June': 'Carl June is the pioneer of CAR-T cell therapy, treated the first pediatric leukemia patient with CAR-T in 2012, UPenn professor',
    'Michel Sadelain': 'Co-developed second-generation CAR-T cells with costimulatory domains, MSKCC, Pioneer in adoptive T cell therapy',
    'Jennifer Doudna': 'Nobel Prize 2020 in Chemistry for CRISPR-Cas9 gene editing, UC Berkeley professor, co-founder of Editas Medicine and Caribou Biosciences',
    'Emmanuelle Charpentier': 'Nobel Prize 2020 in Chemistry for CRISPR-Cas9, Max Planck director, co-inventor of CRISPR gene editing',
    'David Liu': 'Broad Institute, invented base editing and prime editing, founder of Editas Medicine and Beam Therapeutics',
    'Katalin Kariko': 'Nobel Prize 2023 in Medicine for mRNA technology, pioneered modified nucleoside mRNA, UPenn/BioNTech',
    'Drew Weissman': 'Nobel Prize 2023 in Medicine for mRNA technology, developed nucleoside-modified mRNA enabling COVID vaccines, UPenn',
    'Ugur Sahin': 'Co-founder and CEO of BioNTech, led COVID-19 mRNA vaccine development, oncologist and immunologist',
    'Ozlem Tureci': 'Co-founder and CMO of BioNTech, cancer immunology researcher, mRNA vaccine pioneer',
    'Patrick Hsu': 'Arc Institute director, CRISPR innovation, former Salk Institute, developed new CRISPR tools',
    'Jay Keasling': 'UC Berkeley, synthetic biology pioneer, engineered yeast to produce artemisinin, founder of Amyris',
    'Christopher Voigt': 'MIT, synthetic biology, programmed living cells, Cello genetic circuit design language',
    'Pamela Silver': 'Harvard Medical School, synthetic biology, metabolic engineering, systems biology',
    'James Collins': 'MIT, synthetic biology pioneer, synthetic biology for antibiotic discovery, Wyss Institute',
    'Tom Ellis': 'Imperial College London, synthetic biology, yeast chromosome engineering, Sc2.0 project',
    'Eric Topol': 'Scripps Research, digital medicine pioneer, AI in healthcare author, cardiologist',
    'Regina Barzilay': 'MIT, AI for drug discovery, deep learning for molecular property prediction, MacArthur Fellow',
    'Daphne Koller': 'Insitro CEO, co-founder of Coursera, machine learning for biomedicine, Stanford professor',
    'Fei-Fei Li': 'Stanford, AI pioneer, ImageNet creator, now focused on AI in healthcare and ambient intelligence',
    'Wei Wang': 'Peking University, structural biology, cryo-EM',
    'Yigong Shi': 'Westlake University president, structural biologist, previously Princeton and Tsinghua, molecular motors',
    'Hui Cao': 'Peking University, chemical genetics, drug design, chemical biology',
    'Xiaoliang Sunney Xie': 'Peking University / Harvard, single-molecule biophysics pioneer, invented STED and PALM microscopy',
    'Jiankui He': 'Known for creating first gene-edited babies using CRISPR in 2018, controversial figure in gene editing',
    'Lu Chen': 'Fudan University, mRNA vaccine research, infectious diseases',
    'Ning Li': 'Tianjin University, synthetic biology, metabolic engineering',
}


def generate_resume(scholar):
    """使用 AI 生成单个学者的中文履历"""
    name = scholar['name']
    org = scholar['organization'] or '未知机构'
    field = scholar['field'] or '未知领域'
    notes = scholar['notes'] or ''
    hint = SCHOLAR_HINTS.get(name, '')

    prompt = f"""请为以下生物医药领域学者撰写一份中文个人履历（200-400字）。履历应包含：
1. 教育背景（如有）
2. 主要任职机构
3. 核心研究领域和贡献
4. 重要成就（奖项、高影响力论文等）
5. 学术影响力

学者信息：
- 姓名：{name}
- 机构：{org}
- 研究领域：{field}
- 附加信息：{notes}
{f"- 参考资料：{hint}" if hint else ""}

要求：
- 用中文撰写，专业准确
- 突出该学者最核心的贡献和影响力
- 不要编造不确定的信息
- 如果信息不足，请基于已知信息合理组织
- 只输出履历正文，不要标题和其他格式"""

    try:
        resp = requests.post(
            f'{API_BASE}/chat/completions',
            headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-v3.2-exp-thinking',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 600,
            },
            timeout=60
        )
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content'].strip()
            # Remove markdown formatting if present
            content = re.sub(r'^#+\s*', '', content, flags=re.MULTILINE).strip()
            return content
        else:
            print(f"  [AI] API error {resp.status_code}")
            return None
    except Exception as e:
        print(f"  [AI] Request failed: {e}")
        return None


def batch_generate_resumes(force=False):
    """批量生成所有学者的履历"""
    print(f"\n{'='*60}")
    print(f"[履历] 开始生成学者履历 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT * FROM scholars ORDER BY id')
    scholars = [dict(s) for s in c.fetchall()]

    success = 0
    skipped = 0
    failed = 0

    for i, scholar in enumerate(scholars, 1):
        name = scholar['name']

        # Skip if recently updated (within 6 months) and not forced
        if not force and scholar.get('resume_updated_at'):
            try:
                last = datetime.strptime(scholar['resume_updated_at'], '%Y-%m-%d %H:%M:%S')
                delta = (datetime.now() - last).days
                if delta < 180:
                    print(f"  [{i}/{len(scholars)}] {name} - 跳过（{delta}天前已更新）")
                    skipped += 1
                    continue
            except:
                pass

        print(f"  [{i}/{len(scholars)}] {name} ({scholar.get('organization', '')}) - 生成中...", end=' ', flush=True)
        resume = generate_resume(scholar)

        if resume:
            c.execute('UPDATE scholars SET resume = ?, resume_updated_at = ? WHERE id = ?',
                      (resume, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), scholar['id']))
            conn.commit()
            success += 1
            print(f"OK ({len(resume)} chars)")
        else:
            failed += 1
            print("FAILED")

        # Rate limiting: ~1 request per 2 seconds
        if i < len(scholars):
            time.sleep(2)

    conn.close()
    print(f"\n[履历] 完成！成功: {success}, 跳过: {skipped}, 失败: {failed}")
    return success


if __name__ == '__main__':
    force = '--force' in sys.argv
    batch_generate_resumes(force=force)
