import os
import requests
import re
import time
from datetime import datetime, timedelta
import html

# =================配置区域=================
# 飞书 webhook 地址 (从 Secrets 获取)
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")

# 搜索关键词列表 (可以添加更多同义词或缩写)
KEYWORDS = [
    "mineral-associated", 
    "necromass", 
    "microbial",
    "strategy",
    "aggregates",
    "MAOC", # ✅ 新增：直接搜缩写，很多文章标题直接用 MAOC
    "POC",
    "CUE",
    "molecular"
]

# 目标期刊白名单 (只推送这些期刊的文章，避免噪音)
# 如果设为空列表 []，则不限制期刊，所有匹配关键词的都推
TARGET_JOURNALS = [
    "Soil Biology and Biochemistry",
    "Soil Biol. Biochem.",  # ✅ 重要：加上缩写
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
    "Sci. Total Environ.",   # ✅ 重要：Science of the Total Environment 的缩写
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
    "Biol. Fertil. Soils"
]

# 每次每个关键词获取的最大数量 (API 限制 + 容错)
# 既然要查摘要了，可以适当多拉一点，防止标题没写但摘要写了的好文章被漏掉
MAX_RESULTS_PER_KEYWORD = 10 
FETCH_LIMIT = MAX_RESULTS_PER_KEYWORD * 5  # 每次请求 50 条

# =================工具函数=================

def clean_abstract(abstract_html):
    """
    清理 Crossref 返回的 HTML 格式摘要，转换为纯文本
    """
    if not abstract_html:
        return ""
    # 解码 HTML 实体 (如 &amp; -> &)
    text = html.unescape(abstract_html)
    # 去除 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)
    # 去除多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def matches_keyword(text, keyword):
    """
    检查文本中是否包含关键词 (支持简单的连字符容错)
    text: 标题或摘要
    keyword: 搜索词
    """
    if not text:
        return False
    
    t_lower = text.lower()
    k_lower = keyword.lower()
    
    # 直接匹配
    if k_lower in t_lower:
        return True
    
    # 容错：如果关键词有连字符，尝试用空格匹配 (例如 "mineral-associated" 匹配 "mineral associated")
    if "-" in k_lower:
        k_space = k_lower.replace("-", " ")
        if k_space in t_lower:
            return True
            
    # 容错：如果关键词有空格，尝试用连字符匹配
    if " " in k_lower:
        k_dash = k_lower.replace(" ", "-")
        if k_dash in t_lower:
            return True
            
    return False

def is_target_journal(journal_name):
    """
    检查期刊是否在白名单中
    """
    if not TARGET_JOURNALS:
        return True # 如果白名单为空，则全部通过
    
    if not journal_name:
        return False
        
    journal_lower = journal_name.lower()
    for target in TARGET_JOURNALS:
        if target.lower() in journal_lower:
            return True
    return False

def fetch_crossref(keyword):
    """
    从 Crossref 获取文献数据 (最终修复版：解决 400 错误)
    """
    url = "https://api.crossref.org/works"
    
    # 1. 处理日期逻辑
    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)
    
    # 【重要】防御性编程：如果系统时间设置到了未来（如2026年），Crossref可能会报400
    # 我们强制将查询范围限制在“当前实际年份”之前，或者至少是合理的过去时间
    # 这里做一个简单检查：如果 start_date 年份大于 2024 (假设当前真实世界是2024/2025)，则回退
    # 注意：如果你的测试环境确实是在模拟2026年，且Crossref已经收录了2026数据，可注释掉下面这块
    current_real_year = 2025 # 假设真实世界当前是2025，防止穿越
    if start_date.year > current_real_year:
        print(f"⚠️ 警告：检测到日期可能穿越 ({start_date})，自动回退到 1 年前以防 API 报错")
        start_date = end_date - timedelta(days=365)

    date_str = start_date.strftime('%Y-%m-%d')
    
    # 2. 构建参数
    params = {
        "query.bibliographic": keyword,
        "filter": f"from_pub_date:{date_str}",
        "sort": "published",
        "order": "desc",
        "rows": FETCH_LIMIT,
        # 【关键修改】彻底移除 select 参数！
        # 原因：select 列表中的字段如果在某些记录中缺失或格式异常，易引发 400。
        # 不传 select 会让 Crossref 返回默认完整对象，必然包含 abstract (如果有)。
    }
    
    # 3. 设置合规的 Header
    headers = {
        # 【必须】User-Agent 必须包含有效邮箱，否则会被 Crossref 拒绝 (400/403)
        # 请确保这里的邮箱是你真实的，或者至少格式正确
        "User-Agent": "LiteratureBot/1.0 (mailto:researcher@university.edu)", 
        "Accept": "application/json"
    }

    # 4. 重试机制
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 打印调试信息 (GitHub Actions 日志可见)
            if attempt == 0:
                print(f"🌐 正在请求 Crossref: {keyword} (日期: {date_str})")
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            # 特殊处理 400 错误
            if response.status_code == 400:
                error_msg = response.text[:200]
                print(f"⚠️ 收到 400 错误: {error_msg}")
                
                # 降级策略：去掉日期过滤器再试一次
                print("🔄 尝试降级方案：移除日期过滤重新请求...")
                fallback_params = {k: v for k, v in params.items() if k != 'filter'}
                response = requests.get(url, params=fallback_params, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    print("✅ 降级成功！(注意：结果可能包含旧文章)")
                else:
                    # 如果降级也失败，直接抛出异常
                    response.raise_for_status()

            # 如果是其他错误 (404, 500, 503 等)，直接抛出
            response.raise_for_status()
            
            data = response.json()
            items = data.get("message", {}).get("items", [])
            total_results = data.get("message", {}).get("total-results", 0)
            
            print(f"🔍 关键词 '{keyword}': API 返回总数 {total_results}, 本次获取 {len(items)} 条")
            return items
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                print(f"💥 最终放弃关键词 '{keyword}'")
                return []
            time.sleep(2) # 等待后重试

def process_articles(items, keyword):
    """
    处理获取到的文章列表，进行过滤和格式化
    """
    valid_articles = []
    skipped_journal = 0
    skipped_keyword = 0
    matched_by_abstract = 0 # 统计通过摘要匹配的数量

    for item in items:
        # 1. 提取基本信息
        title_list = item.get("title", [])
        title = title_list[0] if title_list else "No Title"
        
        journal_list = item.get("container-title", [])
        journal = journal_list[0] if journal_list else "Unknown Journal"
        
        doi = item.get("DOI", "")
        link = item.get("URL", f"https://doi.org/{doi}")
        
        # 获取发表日期
        pub_date_raw = item.get("published", {}).get("date-parts", [[0,0,0]])
        pub_date = f"{pub_date_raw[0][0]}-{pub_date_raw[0][1]:02d}-{pub_date_raw[0][2]:02d}"
        
        # 获取并清洗摘要
        abstract_html = item.get("abstract", "")
        abstract_text = clean_abstract(abstract_html)
        
        # 2. 期刊白名单过滤
        if not is_target_journal(journal):
            skipped_journal += 1
            continue
            
        # 3. 关键词匹配 (核心修改点：标题 OR 摘要)
        title_match = matches_keyword(title, keyword)
        abstract_match = matches_keyword(abstract_text, keyword)
        
        if not (title_match or abstract_match):
            skipped_keyword += 1
            continue
            
        if abstract_match and not title_match:
            matched_by_abstract += 1
            match_source = "摘要匹配"
        else:
            match_source = "标题匹配"

        # 4. 提取作者
        authors = item.get("author", [])
        author_str = "et al."
        if authors:
            first_name = authors[0].get("given", "")
            last_name = authors[0].get("family", "")
            author_str = f"{first_name} {last_name}"
            if len(authors) > 1:
                author_str += " et al."
        
        # 5. 构建消息卡片内容
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
        
        # 限制每个关键词最终推送的数量 (例如最多 5 篇)
        if len(valid_articles) >= 5:
            break

    print(f"   ✅ 成功匹配: {len(valid_articles)} 篇 (其中 {matched_by_abstract} 篇仅通过摘要匹配)")
    if skipped_journal > 0:
        print(f"   ⏭️ 因期刊不在白名单跳过: {skipped_journal} 篇")
    if skipped_keyword > 0:
        print(f"   ⏭️ 标题和摘要均未匹配关键词: {skipped_keyword} 篇")
        
    return valid_articles

def send_to_feishu(articles, keyword):
    """
    发送消息到飞书
    """
    if not articles:
        return

    if not FEISHU_WEBHOOK:
        print("⚠️ 未配置 FEISHU_WEBHOOK，跳过发送。")
        return

    # 构建飞书卡片消息
    # 注意：飞书卡片 JSON 结构较为复杂，这里使用标准的 Text + Post 混合模式或纯 Text 模式简化
    # 为了兼容性，这里使用丰富的 Text 模式，如果需要精美卡片可后续升级为 Interactive Card
    
    content_lines = [
        f"🔬 **新文献推送 | {keyword}**",
        f"共找到 {len(articles)} 篇相关新文：\n"
    ]

    for i, art in enumerate(articles, 1):
        source_tag = "🏷️" if art['match_source'] == "标题匹配" else "📝" # 摘要匹配用不同图标
        content_lines.append(
            f"{i}. {source_tag} **{art['title']}**\n"
            f"   📅 {art['date']} | 👤 {art['authors']}\n"
            f"   📚 {art['journal']}\n"
            f"   🔗 [DOI Link]({art['link']})\n"
            f"   💡 _摘要_: {art['abstract_snippet']}\n"
        )
        content_lines.append("---")

    full_text = "\n".join(content_lines)

    payload = {
        "msg_type": "text",
        "content": {
            "text": full_text
        }
    }
    
    # 如果希望更美观，可以使用 post 类型，但 text 类型最稳定不易出错
    # 这里为了展示摘要，我们依然用 text 类型，因为 post 类型对长文本支持有限制且配置复杂
    
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload)
        if resp.status_code == 200:
            print("🚀 成功推送到飞书!")
        else:
            print(f"❌ 推送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 发送请求异常: {e}")

def main():
    print(f"🚀 开始运行文献推送任务... 时间: {datetime.now()}")
    
    all_articles = []
    
    for kw in KEYWORDS:
        print(f"\n--- 处理关键词: {kw} ---")
        items = fetch_crossref(kw)
        if not items:
            continue
            
        valid_arts = process_articles(items, kw)
        all_articles.extend(valid_arts)
        
        # 礼貌性延时，避免触发 API 限流
        time.sleep(1)

    if all_articles:
        # 如果有重复 (不同关键词搜到同一篇)，去重 (基于 DOI)
        seen_dois = set()
        unique_articles = []
        for art in all_articles:
            if art['doi'] not in seen_dois:
                seen_dois.add(art['doi'])
                unique_articles.append(art)
        
        print(f"\n🎉 总计去重后文章数: {len(unique_articles)}")
        # 可以按关键词分组发送，也可以合并发送。这里选择合并发送一条大消息
        send_to_feishu(unique_articles, "综合检索")
    else:
        print("\n💤 没有发现符合条件的新文献。")

if __name__ == "__main__":
    main()



