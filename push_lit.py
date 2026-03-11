import os
import requests
import re
import time
import html
from datetime import datetime, timedelta

# =================配置区域=================

# ⚠️ 重要：请确保在 GitHub Secrets 中设置了 FEISHU_WEBHOOK
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")

# 搜索关键词列表
KEYWORDS = [
    "mineral-associated", 
    "necromass", 
    "microbial",
    "strategy",
    "aggregates",
    "MAOC", 
    "POC",
    "CUE",
    "molecular"
]

# 目标期刊白名单 (包含全称和常见缩写)
TARGET_JOURNALS = [
    "Soil Biology and Biochemistry",
    "Soil Biol. Biochem.",
    "Geoderma",
    "Soil Science Society of America Journal",
    "Soil Sci. Soc. Am. J.",
    "European Journal of Soil Science",
    "Eur. J. Soil Sci.",
    "Plant and Soil",
    "Soil Research",
    "Journal of Soils and Sediments",
    "J. Soils Sediments",
    "Catena",
    "Agriculture, Ecosystems & Environment",
    "Agric. Ecosyst. Environ.",
    "Global Change Biology",
    "Sci. Total Environ.",
    "Science of the Total Environment",
    "Environmental Science & Technology",
    "Environ. Sci. Technol.",
    "Biogeochemistry",
    "Soil Use and Management",
    "Applied Soil Ecology",
    "Appl. Soil Ecol.",
    "Nature Geoscience",
    "Nat. Geosci.",
    "Global Biogeochemical Cycles",
    "Glob. Biogeochem. Cycles",
    "Nature Communications",
    "Nat. Commun.",
    "PNAS",
    "Proc. Natl. Acad. Sci. U.S.A.",
    "Geophysical Research Letters",
    "Geophys. Res. Lett.",
    "Vadose Zone Journal",
    "Land Degradation & Development",
    "Land Degradation",
    "Biology and Fertility of Soils",
    "Biol. Fertil. Soils",
    "ISME"
]

# 每个关键词推送的最大篇数
MAX_PUSH_PER_KEYWORD = 5
# API 请求条数 (多拉一点用于过滤)
FETCH_LIMIT = MAX_PUSH_PER_KEYWORD * 5 

# ⚠️ 重要：请替换为你的真实邮箱，否则 Crossref 可能拒绝请求
USER_AGENT_EMAIL = "kaikaimin@163.com" 

# =================工具函数=================

def clean_abstract(abstract_html):
    """清理 HTML 格式的摘要"""
    if not abstract_html:
        return ""
    text = html.unescape(abstract_html)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def matches_keyword(text, keyword):
    """检查文本是否包含关键词 (支持连字符/空格容错)"""
    if not text:
        return False
    
    t_lower = text.lower()
    k_lower = keyword.lower()
    
    if k_lower in t_lower:
        return True
    
    # 容错：连字符 <-> 空格
    if "-" in k_lower:
        if k_lower.replace("-", " ") in t_lower:
            return True
    if " " in k_lower:
        if k_lower.replace(" ", "-") in t_lower:
            return True
            
    return False

def is_target_journal(journal_name):
    """检查期刊是否在白名单中"""
    if not TARGET_JOURNALS:
        return True
    if not journal_name:
        return False
        
    journal_lower = journal_name.lower()
    
    for target in TARGET_JOURNALS:
        if target.lower() in journal_lower:
            return True
    return False

def fetch_crossref(keyword):
    """从 Crossref 获取文献数据"""
    url = "https://api.crossref.org/works"
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)
    
    # 防御未来时间导致 400 错误
    if start_date.year > 2025:
        print(f"⚠️ 警告：日期穿越 ({start_date})，自动回退至 1 年前")
        start_date = end_date - timedelta(days=365)
    
    date_str = start_date.strftime('%Y-%m-%d')
    
    params = {
        "query.bibliographic": keyword,
        "filter": f"from_pub_date:{date_str}",
        "sort": "published",
        "order": "desc",
        "rows": FETCH_LIMIT
    }
    
    headers = {
        "User-Agent": f"LiteratureBot/1.0 (mailto:{USER_AGENT_EMAIL})",
        "Accept": "application/json"
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt == 0:
                print(f"🌐 请求 Crossref: '{keyword}' (日期 >= {date_str})")
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 400:
                print(f"⚠️ 400 错误，尝试降级 (移除日期)...")
                fallback_params = {k: v for k, v in params.items() if k != 'filter'}
                response = requests.get(url, params=fallback_params, headers=headers, timeout=30)
                if response.status_code == 200:
                    print("✅ 降级成功")
                else:
                    response.raise_for_status()
            
            response.raise_for_status()
            data = response.json()
            
            items = data.get("message", {}).get("items", [])
            total = data.get("message", {}).get("total-results", 0)
            print(f"   🔍 总数: {total}, 获取: {len(items)}")
            return items
            
        except Exception as e:
            print(f"   ❌ 尝试 {attempt+1} 失败: {e}")
            if attempt == max_retries - 1:
                return []
            time.sleep(2)

def process_and_send(keyword, items):
    """处理单个关键词的文章并立即发送"""
    if not items:
        print(f"   💤 无数据，跳过推送。")
        return

    valid_articles = []
    seen_dois = set()
    matched_by_abstract_count = 0

    for item in items:
        # 提取字段
        title_list = item.get("title", [])
        title = title_list[0] if title_list else "No Title"
        
        journal_list = item.get("container-title", [])
        journal = journal_list[0] if journal_list else "Unknown Journal"
        
        doi = item.get("DOI", "")
        
        # 去重检查
        if doi in seen_dois:
            continue
        seen_dois.add(doi)
        
        link = item.get("URL", f"https://doi.org/{doi}")
        
        pub_date_raw = item.get("published", {}).get("date-parts", [[0,0,0]])
        try:
            pub_date = f"{pub_date_raw[0][0]}-{pub_date_raw[0][1]:02d}-{pub_date_raw[0][2]:02d}"
        except:
            pub_date = "Unknown Date"
        
        # 清洗摘要
        abstract_html = item.get("abstract", "")
        abstract_text = clean_abstract(abstract_html)
        
        # 1. 期刊过滤
        if not is_target_journal(journal):
            continue
            
        # 2. 关键词匹配 (标题 OR 摘要)
        title_match = matches_keyword(title, keyword)
        abstract_match = matches_keyword(abstract_text, keyword)
        
        if not (title_match or abstract_match):
            continue
            
        if abstract_match and not title_match:
            matched_by_abstract_count += 1
            match_source = "摘要匹配"
        else:
            match_source = "标题匹配"

        # 3. 提取作者
        authors = item.get("author", [])
        author_str = "et al."
        if authors:
            first = authors[0].get("given", "")
            last = authors[0].get("family", "")
            author_str = f"{first} {last}"
            if len(authors) > 1:
                author_str += " et al."
        
        # 4. 构建对象
        article_info = {
            "title": title,
            "journal": journal,
            "authors": author_str,
            "date": pub_date,
            "link": link,
            "doi": doi,
            "match_source": match_source,
            "abstract_snippet": abstract_text[:200] + "..." if len(abstract_text) > 200 else abstract_text
        }
        valid_articles.append(article_info)
        
        # 达到上限即停止
        if len(valid_articles) >= MAX_PUSH_PER_KEYWORD:
            break

    # 打印统计
    print(f"   ✅ 筛选后: {len(valid_articles)} 篇 (其中 {matched_by_abstract_count} 篇仅摘要匹配)")
    
    # 发送消息
    if valid_articles:
        send_to_feishu(valid_articles, keyword)
    else:
        print(f"   💤 无符合期刊/关键词条件的文章，跳过推送。")

def send_to_feishu(articles, keyword):
    """发送单个关键词的消息到飞书"""
    if not FEISHU_WEBHOOK:
        print("   ⚠️ 未配置 Webhook，跳过发送。")
        return

    content_lines = [
        f"🔬 **新文献推送 | 关键词: {keyword}**",
        f"最新 {len(articles)} 篇相关好文：\n"
    ]

    for i, art in enumerate(articles, 1):
        icon = "🏷️" if art['match_source'] == "标题匹配" else "📝"
        content_lines.append(
            f"{i}. {icon} **{art['title']}**\n"
            f"   📅 {art['date']} | 👤 {art['authors']}\n"
            f"   📚 {art['journal']}\n"
            f"   🔗 [DOI Link]({art['link']})\n"
            f"   💡 _摘要_: {art['abstract_snippet']}\n"
            "---"
        )

    payload = {
        "msg_type": "text",
        "content": {"text": "\n".join(content_lines)}
    }
    
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload)
        if resp.status_code == 200:
            print(f"   🚀 已推送到飞书!")
        else:
            print(f"   ❌ 推送失败: {resp.text}")
    except Exception as e:
        print(f"   ❌ 发送异常: {e}")

def main():
    print(f"🚀 启动任务: {datetime.now()}")
    print(f"📋 关键词列表: {', '.join(KEYWORDS)}")
    print("-" * 30)
    
    for kw in KEYWORDS:
        print(f"\n>>> 处理关键词: [{kw}]")
        items = fetch_crossref(kw)
        
        # 处理并立即发送
        process_and_send(kw, items)
        
        # 礼貌延时，避免触发 API 限流 (每个关键词之间停顿)
        time.sleep(1.5)

    print("\n" + "=" * 30)
    print("🎉 所有关键词处理完毕！")

if __name__ == "__main__":
    main()


