from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import time
import requests
import statsapi
import sys

# ---------------------------------------------------------
# 공통 설정
TELEGRAM_BOT_TOKEN = "7713068391:AAFIOAa_olH-FHzrIJsDsgDQXGMZ0FW5PUE"
TELEGRAM_CHAT_ID = "-5420806624"
KST = timezone(timedelta(hours=9))

# MLB 팀 이름 한글 매핑
TEAM_NAME_KOR = {
    "Baltimore Orioles": "볼티모어 오리올스", "Boston Red Sox": "보스턴 레드삭스",
    "New York Yankees": "뉴욕 양키스", "Tampa Bay Rays": "탬파베이 레이스",
    "Toronto Blue Jays": "토론토 블루제이스", "Chicago White Sox": "시카고 화이트삭스",
    "Cleveland Guardians": "클리블랜드 가디언스", "Detroit Tigers": "디트로이트 타이거스",
    "Kansas City Royals": "캔자스시티 로열스", "Minnesota Twins": "미네소타 트윈스",
    "Houston Astros": "휴스턴 애스트로스", "Los Angeles Angels": "로스앤젤레스 에인절스",
    "Oakland Athletics": "오클랜드 애슬레틱스", "Athletics": "애슬레틱스",
    "Seattle Mariners": "시애틀 매리너스", "Texas Rangers": "텍사스 레인저스",
    "Atlanta Braves": "애틀랜타 브레이브스", "Miami Marlins": "마이애미 말린스",
    "New York Mets": "뉴욕 메츠", "Philadelphia Phillies": "필라델피아 필리스",
    "Washington Nationals": "워싱턴 내셔널스", "Chicago Cubs": "시카고 컵스",
    "Cincinnati Reds": "신시내티 레즈", "Milwaukee Brewers": "밀워키 브루어스",
    "Pittsburgh Pirates": "피츠버그 파이리츠", "St. Louis Cardinals": "세인트루이스 카디널스",
    "Arizona Diamondbacks": "애리조나 다이아몬드백스", "Colorado Rockies": "콜로라도 로키스",
    "Los Angeles Dodgers": "로스앤젤레스 다저스", "San Diego Padres": "샌디에이고 파드리스",
    "San Francisco Giants": "샌프란시스코 자이언츠"
}

# WNBA 팀 이름 한글 매핑
WNBA_TEAM_NAME_KOR = {
    "Golden State Valkyries": "골든스테이트 발키리스",
    "Atlanta Dream": "애틀랜타 드림", "Chicago Sky": "시카고 스카이",
    "Connecticut Sun": "코네티컷 선", "Dallas Wings": "댈러스 윙스",
    "Indiana Fever": "인디애나 피버", "Las Vegas Aces": "라스베이거스 에이시스",
    "Los Angeles Sparks": "로스앤젤레스 스팍스", "Minnesota Lynx": "미네소타 링크스",
    "New York Liberty": "뉴욕 리버티", "Phoenix Mercury": "피닉스 머큐리",
    "Seattle Storm": "시애틀 스톰", "Washington Mystics": "워싱턴 미스틱스"
}

def translate_team(eng_name): 
    return TEAM_NAME_KOR.get(eng_name, eng_name)

def translate_wnba_team(eng_name):
    return WNBA_TEAM_NAME_KOR.get(eng_name, eng_name)

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try: 
        requests.post(url, json=payload, timeout=10)
    except: 
        pass

def convert_utc_to_kst(utc_str):
    try:
        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        kst_dt = utc_dt.astimezone(KST)
        return kst_dt.strftime("%m월 %d일 (%a) %H:%M")
    except:
        return utc_str


# =========================================================
# 1. WNBA 경기 알림 (쿼터별 누적 및 한글 팀명 적용)
# =========================================================
wnba_live_status = {}

def fetch_wnba_data():
    now_kst = datetime.now(KST)
    dates_to_query = [
        now_kst.strftime("%Y%m%d"),
        (now_kst - timedelta(days=1)).strftime("%Y%m%d")
    ]
    
    all_events = []
    seen_game_ids = set()

    for target_str in dates_to_query:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={target_str}"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                events = res.json().get('events', [])
                for ev in events:
                    g_id = ev.get('id')
                    if g_id and g_id not in seen_game_ids:
                        seen_game_ids.add(g_id)
                        all_events.append(ev)
        except:
            pass
            
    today_kst_str = now_kst.strftime("%Y-%m-%d")
    filtered_events = []
    for ev in all_events:
        utc_date_str = ev.get('date', '')
        try:
            utc_dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
            kst_dt = utc_dt.astimezone(KST)
            if kst_dt.strftime("%Y-%m-%d") == today_kst_str:
                filtered_events.append(ev)
        except:
            filtered_events.append(ev)
            
    return filtered_events

def run_wnba_bot():
    print("🏀 WNBA 쿼터별 누적 및 최종 스코어 알림 봇 실행 중...")
    last_checked_date = ""

    while True:
        today_str = datetime.now(KST).strftime("%Y%m%d")
        if today_str != last_checked_date:
            wnba_live_status.clear()
            last_checked_date = today_str

        events = fetch_wnba_data()
        for game in events:
            game_id = game['id']
            status = game['status']['type']['state']
            detail = game['status']['type']['detail'].lower() 
            game_date_utc = game.get('date', '')
            kst_time_str = convert_utc_to_kst(game_date_utc)
            
            if not game.get('competitions'): continue
                
            competition = game['competitions'][0]
            competitors = competition['competitors']
            
            away_eng = competitors[1]['team']['displayName']
            home_eng = competitors[0]['team']['displayName']
            away = translate_wnba_team(away_eng)
            home = translate_wnba_team(home_eng)
            
            matchup_str = f"{home} vs {away}"

            if game_id not in wnba_live_status:
                wnba_live_status[game_id] = {
                    "matchup": matchup_str, 
                    "sent_quarters": set(),
                    "final_sent": False
                }
                if status == "pre":
                    send_telegram_message(f"🏀 **[WNBA 오늘 경기 일정]**\n{matchup_str}\n시간: {kst_time_str} (KST)\n상태: 경기 전")

            game_info = wnba_live_status[game_id]
            away_linescores = competitors[1].get('linescores', [])
            home_linescores = competitors[0].get('linescores', [])
            is_final = (status == 'post')

            quarter_keywords = {
                0: ["1st", "end of 1st", "1st quarter"],
                1: ["halftime", "end of 2nd", "2nd quarter", "2nd"],
                2: ["3rd", "end of 3rd", "3rd quarter"],
                3: ["4th", "end of 4th", "regulation", "final", "post"]
            }

            for q_idx in range(len(away_linescores)):
                if q_idx in game_info["sent_quarters"]: continue

                q_name = f"{q_idx + 1}쿼터" if q_idx < 4 else f"연장 {q_idx - 3}차"
                is_quarter_ended = False

                if is_final:
                    is_quarter_ended = True 
                else:
                    if q_idx < len(away_linescores) and 'value' in away_linescores[q_idx]:
                        keywords = quarter_keywords.get(q_idx, ["ot", "overtime"])
                        if any(kw in detail for kw in keywords) or q_idx >= 4:
                            is_quarter_ended = True

                if is_quarter_ended:
                    q_score_lines = []
                    home_total = 0
                    away_total = 0
                    
                    for qi in range(q_idx + 1):
                        if qi < len(home_linescores) and qi < len(away_linescores):
                            hs = int(home_linescores[qi].get('value', 0))
                            as_ = int(away_linescores[qi].get('value', 0))
                            home_total += hs
                            away_total += as_
                            q_label = f"{qi+1}Q" if qi < 4 else f"OT{qi-3}"
                            q_score_lines.append(f"• {q_label}: {home} {hs} : {as_} {away}")

                    if is_final and q_idx == len(away_linescores) - 1 and not game_info["final_sent"]:
                        header = "🏁 **WNBA 최종 경기 결과**"
                        ot_text = f" (연장 포함)" if len(away_linescores) > 4 else ""
                        final_score_str = f"\n🏆 **최종 스코어{ot_text}**: {home} {home_total} : {away_total} {away}"
                        
                        score_details = "\n".join(q_score_lines)
                        msg = f"{header}\n\n{matchup_str}\n{score_details}\n{final_score_str}"
                        send_telegram_message(msg)
                        game_info["final_sent"] = True
                        game_info["sent_quarters"].add(q_idx)
                    
                    elif not is_final:
                        header = f"🏀 **WNBA {q_name} 종료 스코어**"
                        score_details = "\n".join(q_score_lines)
                        msg = f"{header}\n\n{matchup_str}\n{score_details}\n누적 합계: {home} {home_total} : {away_total} {away}"
                        send_telegram_message(msg)
                        game_info["sent_quarters"].add(q_idx)

        time.sleep(60)


# =========================================================
# 2. MLB 경기 모니터링
# =========================================================
match_live_status = {}

def get_games_for_kst_date(kst_date_str):
    game_list = []
    try:
        target_dt = datetime.strptime(kst_date_str, "%Y-%m-%d")
        start_date_str = (target_dt - timedelta(days=1)).strftime("%m/%d/%Y")
        end_date_str = target_dt.strftime("%m/%d/%Y")
        schedules = statsapi.schedule(start_date=start_date_str, end_date=end_date_str)
        
        match_count_map = {}
        valid_schedules = []
        
        for g in schedules:
            game_datetime_utc = g.get("game_datetime", "")
            if not game_datetime_utc: continue
            utc_time = datetime.fromisoformat(game_datetime_utc.replace("Z", "+00:00"))
            kst_time = utc_time.astimezone(KST)
            if kst_time.strftime("%Y-%m-%d") == kst_date_str:
                away = g.get('away_name')
                home = g.get('home_name')
                match_key = f"{away}_{home}"
                match_count_map[match_key] = match_count_map.get(match_key, 0) + 1
                valid_schedules.append((g, kst_time))

        dh_tracker = {}
        for g, kst_time in valid_schedules:
            game_pk = g.get("game_id")
            away_name = translate_team(g.get('away_name'))
            home_name = translate_team(g.get('home_name'))
            match_key = f"{g.get('away_name')}_{g.get('home_name')}"
            
            dh_suffix = ""
            if match_count_map.get(match_key, 1) > 1:
                dh_tracker[match_key] = dh_tracker.get(match_key, 0) + 1
                dh_suffix = f" (DH-{dh_tracker[match_key]})"

            matchup_str = f"{home_name} vs {away_name}{dh_suffix}"

            game_list.append({
                "game_pk": game_pk,
                "matchup": matchup_str,
                "away_team": away_name,
                "home_team": home_name,
            })
    except: pass
    return game_list

def monitor_single_game(game_info):
    game_pk = game_info["game_pk"]
    matchup = game_info["matchup"]
    away_team_name = game_info["away_team"]
    home_team_name = game_info["home_team"]

    match_live_status[game_pk] = {
        "matchup": matchup, 
        "first_inning_result": "진행 중", 
        "fifth_inning_result": "진행 중", 
        "final_result": "진행 중", 
        "first_walk_info": "없음",
        "current_progress": "경기 전"
    }
    
    notified_5th, notified_walk, notified_extra, notified_final = False, False, False, False
    last_sent_1st_score = None

    while not notified_final:
        try:
            game_data = statsapi.get("game", {"gamePk": game_pk})
            linescore = statsapi.get("game_linescore", {"gamePk": game_pk})
            innings = linescore.get("innings", [])
            game_status = game_data.get("gameData", {}).get("status", {}).get("abstractGameState")
            curr_inning = linescore.get("currentInning", 1)
            inning_state = linescore.get("inningState", "")

            if game_status == "Final":
                match_live_status[game_pk]["current_progress"] = "경기 종료"
            elif game_status == "Preview" or not game_status:
                match_live_status[game_pk]["current_progress"] = "경기 전"
            else:
                half_str = "초" if inning_state == "Top" else ("말" if inning_state == "Bottom" else inning_state)
                match_live_status[game_pk]["current_progress"] = f"{curr_inning}회 {half_str}"

            if len(innings) >= 1:
                inn_1 = innings[0]
                a_1 = inn_1.get("away", {}).get("runs", 0)
                h_1 = inn_1.get("home", {}).get("runs", 0)
                current_1st_score = f"{h_1}:{a_1}"
                
                is_1st_active_scoring = (curr_inning == 1 and (a_1 > 0 or h_1 > 0))
                is_1st_ended = (curr_inning > 1) or (curr_inning == 1 and inning_state == "End")
                
                if (is_1st_active_scoring or is_1st_ended) and current_1st_score != last_sent_1st_score:
                    match_live_status[game_pk]["first_inning_result"] = current_1st_score
                    send_telegram_message(f"⚾ **[MLB 1이닝 결과]**\n{matchup}\n{h_1} : {a_1}")
                    last_sent_1st_score = current_1st_score

            if not notified_5th and len(innings) >= 5:
                if (curr_inning > 5) or (curr_inning == 5 and inning_state == "End"):
                    a_5 = sum(i.get("away", {}).get("runs", 0) for i in innings[:5] if "away" in i)
                    h_5 = sum(i.get("home", {}).get("runs", 0) for i in innings[:5] if "home" in i)
                    match_live_status[game_pk]["fifth_inning_result"] = f"{h_5}:{a_5}"
                    send_telegram_message(f"📊 **[MLB 5이닝 종료]**\n{matchup}\n{h_5} : {a_5}")
                    notified_5th = True

            if curr_inning >= 10 and not notified_extra:
                reg_a = sum(i.get("away", {}).get("runs", 0) for i in innings[:9] if "away" in i)
                reg_h = sum(i.get("home", {}).get("runs", 0) for i in innings[:9] if "home" in i)
                send_telegram_message(f"🚨 **[MLB 연장전 진입]**\n{matchup}\n9회 말 종료 스코어: {reg_h} : {reg_a}")
                notified_extra = True

            if game_status == "Final":
                curr_a = linescore.get("teams", {}).get("away", {}).get("runs", 0)
                curr_h = linescore.get("teams", {}).get("home", {}).get("runs", 0)
                if len(innings) > 9:
                    reg_a = sum(i.get("away", {}).get("runs", 0) for i in innings[:9] if "away" in i)
                    reg_h = sum(i.get("home", {}).get("runs", 0) for i in innings[:9] if "home" in i)
                    final_str = f"정규 {reg_h}:{reg_a} → 최종 {curr_h}:{curr_a} (종료)"
                else:
                    final_str = f"{curr_h}:{curr_a} (종료)"
                match_live_status[game_pk]["final_result"] = final_str
                send_telegram_message(f"🏁 **[MLB 경기 종료]**\n{matchup}\n결과: {final_str}")
                notified_final = True

            if not notified_walk:
                pbp = statsapi.get("game_playByPlay", {"gamePk": game_pk})
                for play in pbp.get("allPlays", []):
                    if play.get("result", {}).get("eventType") == "walk":
                        inn = play.get("about", {}).get("inning")
                        is_top = play.get("about", {}).get("isTopInning", True)
                        half = "초" if is_top else "말"
                        walk_team = away_team_name if is_top else home_team_name
                        batter = play.get("matchup", {}).get("batter", {}).get("fullName", "")
                        match_live_status[game_pk]["first_walk_info"] = f"{inn}회{half} | {walk_team} ({batter})"
                        send_telegram_message(f"🚶 **[MLB 첫 볼넷]** {matchup}\n{inn}회{half} | {walk_team} ({batter})")
                        notified_walk = True
                        break
        except: pass
        time.sleep(45)

def run_mlb_scheduler(executor):
    print("⚾ MLB 경기 모니터링 스케줄러 실행 중...")
    monitored_games = set()
    last_date_str = ""

    while True:
        try:
            kst_now = datetime.now(KST)
            today_str = kst_now.strftime("%Y-%m-%d")

            if today_str != last_date_str:
                last_date_str = today_str
                monitored_games.clear()
                match_live_status.clear()

            games = get_games_for_kst_date(today_str)
            for game in games:
                g_pk = game["game_pk"]
                if g_pk not in monitored_games:
                    monitored_games.add(g_pk)
                    executor.submit(monitor_single_game, game)
        except:
            pass
        
        time.sleep(600)


# =========================================================
# 3. 텔레그램 리스너
# =========================================================
def listen_telegram_commands():
    offset = 0
    while True:
        try:
            res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 30})
            for r in res.json().get("result", []):
                offset = r["update_id"] + 1
                text = r.get("message", {}).get("text", "").strip().lower()
                
                if text == "1":
                    msg = "📊 **[MLB 실시간 요약]**\n" + "\n".join([
                        f"\n⚾ {i['matchup']} ({i['current_progress']})\n• 스코어: {i['first_inning_result']} (1이닝), {i['fifth_inning_result']} (5이닝)\n• 첫 볼넷: {i['first_walk_info']}\n• 결과: {i['final_result']}\n──────────────────" 
                        for i in match_live_status.values()
                    ])
                    send_telegram_message(msg if match_live_status else "진행 중인 MLB 경기가 없습니다.")
                
                elif text == "2" or text == "wnba":
                    events = fetch_wnba_data()
                    if not events:
                        send_telegram_message("오늘 예정된 WNBA 경기가 없습니다.")
                    else:
                        msg = "🏀 **[WNBA 실시간 요약 (한국 시간)]**\n"
                        for ev in events:
                            comp = ev.get('competitions', [{}])[0]
                            comps = comp.get('competitors', [])
                            if len(comps) == 2:
                                away_t = translate_wnba_team(comps[1]['team']['displayName'])
                                home_t = translate_wnba_team(comps[0]['team']['displayName'])
                                a_sc = comps[1].get('score', '0')
                                h_sc = comps[0].get('score', '0')
                                status_detail = ev.get('status', {}).get('type', {}).get('detail', '진행 전')
                                kst_time = convert_utc_to_kst(ev.get('date', ''))
                                msg += f"\n• {home_t} {h_sc} : {a_sc} {away_t}\n  📊 상태: {status_detail}\n  ⏰ 시작 시간: {kst_time}\n──────────────────"
                        send_telegram_message(msg)
        except: time.sleep(2)

if __name__ == "__main__":
    try:
        executor = ThreadPoolExecutor(max_workers=20)
        executor.submit(listen_telegram_commands)
        executor.submit(run_wnba_bot)
        run_mlb_scheduler(executor)
    except KeyboardInterrupt:
        print("\n🛑 프로그램 종료.")
        sys.exit(0)
