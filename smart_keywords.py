"""
智能关键词提取模块
根据市场标题和分类，自动生成最佳搜索关键词
"""
import re


def extract_smart_keywords(title, category="Other"):
    """
    智能提取搜索关键词
    根据市场类型和标题内容，自动生成多个相关搜索词
    """
    keywords = []
    
    # 1. 基础清理
    clean_title = title.replace("?", "").replace("!", "").strip()
    
    # 2. 根据分类生成关键词
    if category == "Crypto":
        keywords.extend(_crypto_keywords(clean_title))
    elif category == "Politics":
        keywords.extend(_politics_keywords(clean_title))
    elif category == "Sports":
        keywords.extend(_sports_keywords(clean_title))
    elif category == "Entertainment":
        keywords.extend(_entertainment_keywords(clean_title))
    elif category == "Technology":
        keywords.extend(_technology_keywords(clean_title))
    elif category == "Economics":
        keywords.extend(_economics_keywords(clean_title))
    else:
        keywords.extend(_general_keywords(clean_title))
    
    # 3. 去重并限制数量
    unique_keywords = list(dict.fromkeys(keywords))[:5]
    
    return unique_keywords


def _crypto_keywords(title):
    """加密货币市场关键词"""
    keywords = []
    
    # 提取代币名称
    coins = re.findall(r'\b(BTC|Bitcoin|ETH|Ethereum|SOL|Solana|DOGE|Dogecoin|XRP|Ripple|ADA|Cardano|DOT|Polkadot|AVAX|Avalanche|MATIC|Polygon|LINK|Chainlink|UNI|Uniswap|AAVE|Maker|MKR)\b', title, re.IGNORECASE)
    
    if coins:
        coin = coins[0].upper()
        keywords.append(f"{coin} price news today")
        keywords.append(f"{coin} market analysis")
        keywords.append(f"crypto {coin} latest")
    
    # 提取价格相关
    price_match = re.search(r'\$[\d,]+', title)
    if price_match:
        price = price_match.group()
        keywords.append(f"Bitcoin {price} prediction")
    
    # 通用加密关键词
    if not keywords:
        keywords.append(f"crypto {title[:30]}")
        keywords.append(f"cryptocurrency news today")
    
    return keywords


def _politics_keywords(title):
    """政治市场关键词"""
    keywords = []
    
    # 提取人名
    people = re.findall(r'\b(Trump|Biden|Harris|DeSantis|Obama|Putin|Xi Jinping|Zelensky|Modi|Erdogan|Macron|Scholz)\b', title, re.IGNORECASE)
    
    if people:
        person = people[0]
        keywords.append(f"{person} latest news today")
        keywords.append(f"{person} policy announcement")
    
    # 提取政策关键词
    policy_words = re.findall(r'\b(president|election|vote|congress|senate|impeach|resign|war|peace|sanction|tariff|trade|tax|healthcare|immigration|climate)\b', title, re.IGNORECASE)
    
    if policy_words:
        policy = policy_words[0]
        keywords.append(f"{policy} news today")
    
    # 提取国家/地区
    countries = re.findall(r'\b(US|USA|China|Russia|Ukraine|Iran|Israel|Taiwan|India|EU|Europe|UK|Japan|Korea|North Korea)\b', title, re.IGNORECASE)
    
    if countries:
        country = countries[0]
        keywords.append(f"{country} politics news")
    
    # 通用政治关键词
    if not keywords:
        keywords.append(f"politics {title[:30]}")
        keywords.append(f"political news today")
    
    return keywords


def _sports_keywords(title):
    """体育市场关键词"""
    keywords = []
    
    # 提取运动类型
    sports = re.findall(r'\b(NBA|NFL|MLB|NHL|UFC|FIFA|World Cup|Olympics|Champions League|Premier League|La Liga|Serie A|Bundesliga)\b', title, re.IGNORECASE)
    
    if sports:
        sport = sports[0]
        keywords.append(f"{sport} news today")
        keywords.append(f"{sport} latest results")
    
    # 提取球队/选手
    teams = re.findall(r'\b(Lakers|Warriors|Celtics|Bulls|Heat|Knicks|Yankees|Red Sox|Cowboys|Patriots|Packers|Chiefs|Man United|Liverpool|Barcelona|Real Madrid|Bayern|PSG)\b', title, re.IGNORECASE)
    
    if teams:
        team = teams[0]
        keywords.append(f"{team} news today")
        keywords.append(f"{team} latest results")
    
    # 提取选手名
    athletes = re.findall(r'\b(LeBron|Curry|Durant|Messi|Ronaldo|Serena|Federer|Djokovic|Nadal|McGregor|Khabib|Jon Jones|Canelo|Mayweather)\b', title, re.IGNORECASE)
    
    if athletes:
        athlete = athletes[0]
        keywords.append(f"{athlete} latest news")
    
    # 年份
    year_match = re.search(r'20\d{2}', title)
    year = year_match.group() if year_match else "2026"
    
    # 通用体育关键词
    if not keywords:
        keywords.append(f"sports {title[:30]} {year}")
        keywords.append(f"sports news today {year}")
    
    return keywords


def _entertainment_keywords(title):
    """娱乐市场关键词"""
    keywords = []
    
    # 提取名人
    celebrities = re.findall(r'\b(Trump|Elon Musk|Taylor Swift|Beyoncé|Drake|Kanye|Kim Kardashian|Jeff Bezos|Mark Zuckerberg|Sam Altman|Cristiano Ronaldo|Lionel Messi)\b', title, re.IGNORECASE)
    
    if celebrities:
        celeb = celebrities[0]
        keywords.append(f"{celeb} news today")
        keywords.append(f"{celeb} latest update")
    
    # 提取娱乐类型
    entertainment = re.findall(r'\b(movie|film|album|song|concert|tour|Grammy|Oscar|Emmy|Netflix|Disney|Marvel|DC|Star Wars|Game of Thrones|GTA|Call of Duty|Fortnite|Minecraft)\b', title, re.IGNORECASE)
    
    if entertainment:
        ent = entertainment[0]
        keywords.append(f"{ent} news today")
        keywords.append(f"{ent} release date")
    
    # 提取音乐艺术家
    artists = re.findall(r'\b(Rihanna|Beyoncé|Taylor Swift|Drake|Ed Sheeran|Adele|Billie Eilish|The Weeknd|Bad Bunny|BTS|Blackpink|Playboi Carti|Kanye West)\b', title, re.IGNORECASE)
    
    if artists:
        artist = artists[0]
        keywords.append(f"{artist} new music 2026")
        keywords.append(f"{artist} album release")
    
    # 通用娱乐关键词
    if not keywords:
        keywords.append(f"entertainment {title[:30]}")
        keywords.append(f"celebrity news today")
    
    return keywords


def _technology_keywords(title):
    """科技市场关键词"""
    keywords = []
    
    # 提取科技公司
    companies = re.findall(r'\b(Apple|Google|Microsoft|Amazon|Meta|Tesla|NVIDIA|OpenAI|Anthropic|DeepMind|SpaceX|Twitter|X|TikTok|ByteDance|Samsung|Intel|AMD|Qualcomm)\b', title, re.IGNORECASE)
    
    if companies:
        company = companies[0]
        keywords.append(f"{company} news today")
        keywords.append(f"{company} latest update")
    
    # 提取技术关键词
    tech = re.findall(r'\b(AI|artificial intelligence|machine learning|blockchain|crypto|quantum|robotics|autonomous|self-driving|VR|AR|metaverse|5G|6G|cloud|cybersecurity|data|algorithm)\b', title, re.IGNORECASE)
    
    if tech:
        technology = tech[0]
        keywords.append(f"{technology} news today")
        keywords.append(f"{technology} breakthrough")
    
    # 通用科技关键词
    if not keywords:
        keywords.append(f"technology {title[:30]}")
        keywords.append(f"tech news today")
    
    return keywords


def _economics_keywords(title):
    """经济市场关键词"""
    keywords = []
    
    # 提取经济指标
    indicators = re.findall(r'\b(GDP|inflation|interest rate|Fed|Federal Reserve|unemployment|jobs|CPI|PPI|retail sales|housing|stock market|S&P 500|Dow Jones|NASDAQ|Bitcoin|gold|oil|crude)\b', title, re.IGNORECASE)
    
    if indicators:
        indicator = indicators[0]
        keywords.append(f"{indicator} news today")
        keywords.append(f"{indicator} market update")
    
    # 提取国家经济
    countries = re.findall(r'\b(US|USA|China|EU|Europe|UK|Japan|India|Germany|France|Canada|Australia)\b', title, re.IGNORECASE)
    
    if countries:
        country = countries[0]
        keywords.append(f"{country} economy news")
    
    # 通用经济关键词
    if not keywords:
        keywords.append(f"economy {title[:30]}")
        keywords.append(f"economic news today")
    
    return keywords


def _general_keywords(title):
    """通用市场关键词"""
    keywords = []
    
    # 提取关键名词（3个字母以上的单词）
    words = re.findall(r'\b[A-Za-z]{4,}\b', title)
    
    # 过滤常见停用词
    stop_words = {'will', 'before', 'after', 'during', 'this', 'that', 'with', 'from', 'they', 'have', 'been', 'said', 'each', 'which', 'their', 'time', 'about', 'would', 'make', 'like', 'just', 'over', 'such', 'take', 'year', 'than', 'them', 'some', 'what', 'when', 'your', 'more', 'very', 'into', 'could', 'other'}
    
    important_words = [w for w in words if w.lower() not in stop_words][:3]
    
    if important_words:
        keywords.append(" ".join(important_words) + " news today")
        keywords.append(" ".join(important_words) + " latest")
    
    # 通用关键词
    if not keywords:
        keywords.append(f"news {title[:30]}")
        keywords.append(f"latest news today")
    
    return keywords


def get_search_queries(title, category="Other", max_queries=3):
    """
    获取搜索查询列表
    返回多个相关搜索词，用于不同新闻源
    """
    keywords = extract_smart_keywords(title, category)
    
    # 为每个关键词生成不同变体
    queries = []
    for kw in keywords[:max_queries]:
        queries.append(kw)
    
    # 如果关键词不足，补充通用查询
    if len(queries) < max_queries:
        clean_title = title.replace("?", "").replace("!", "").strip()
        if clean_title not in queries:
            queries.append(clean_title[:50])
    
    return queries[:max_queries]


# 测试
if __name__ == "__main__":
    test_cases = [
        ("Will Bitcoin hit $100k before 2027?", "Crypto"),
        ("Trump out as President before GTA VI?", "Politics"),
        ("Lakers win NBA Championship 2026?", "Sports"),
        ("Rihanna release new album before 2027?", "Entertainment"),
        ("Apple release AR glasses in 2026?", "Technology"),
        ("US recession in 2026?", "Economics"),
        ("Jesus Christ return before GTA VI?", "Other"),
    ]
    
    print("=" * 60)
    print("🧠 智能关键词提取测试")
    print("=" * 60)
    
    for title, category in test_cases:
        print(f"\n📌 市场: {title}")
        print(f"   分类: {category}")
        queries = get_search_queries(title, category)
        for i, q in enumerate(queries, 1):
            print(f"   搜索词{i}: {q}")
        print()
