"""
meta_api_validator.py
────────────────────────────────────────────────────────────────────
DB 구축 전, 스키마의 모든 컬럼이 Meta API로 정상 수집되는지 사전 검증.

[입력 필요]
  CONFIG 딕셔너리에 아래 4가지 값을 채워넣고 실행.
  META_ACCESS_TOKEN 은 같은 디렉터리의 .env 에서 자동 로드됨.

[실행 방법]
  pip install requests python-dotenv
  python meta_api_validator.py
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# .env 로드 (스크립트와 같은 디렉터리 기준)
load_dotenv(Path(__file__).parent / ".env")

# ====================================================================
# ★ 검증 대상 입력값 ★
# ====================================================================
CONFIG = {
    "access_token":            os.environ["META_ACCESS_TOKEN"],  # .env 에서 자동 로드
    "conversion_campaign_id":  "120239737006050208",   # 구매전환 캠페인
    "traffic_campaign_id":     "120240002851690208",   # 트래픽 캠페인
    # 영상 소재 & 댓글 성과가 있는 캠페인 (선택 입력 — 비우면 해당 섹션 건너뜀)
    "extra_campaign_id":       "120239085948890765",
    "extra_campaign_label":    "영상광고 포함 캠페인",           # 리포트에 표시될 이름
    "ig_reels_media_id":       "17850471384620280",    # 릴스 게시물 (숫자 ID)
    "ig_carousel_media_id":    "18120264286573298",    # 캐러셀 게시물 (숫자 ID)
    # IG 계정 ID (fb_ig_id) — 위 캠페인과 연결된 인스타그램 계정
    # 광고계정에서 connected_instagram_account.id 로 확인 가능
    "ig_user_id":              "17841468841982301",
}

# 광고 성과 조회 범위 (Facebook Ads API — 기간 제한 없음)
DATE_START = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
DATE_END   = datetime.now().strftime("%Y-%m-%d")

# IG Insights 조회 범위 (since/until 최대 30일 제한)
IG_DATE_START = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
IG_DATE_END   = DATE_END

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
# ====================================================================


# ====================================================================
# 캠페인 목록 헬퍼 — extra_campaign_id 입력 시 자동 포함
# ====================================================================
def campaign_list() -> list[tuple[str, str]]:
    """검증 대상 캠페인 (label, campaign_id) 목록. extra가 설정된 경우 포함."""
    camps = [
        ("구매전환 캠페인", CONFIG["conversion_campaign_id"]),
        ("트래픽 캠페인",   CONFIG["traffic_campaign_id"]),
    ]
    if not CONFIG["extra_campaign_id"].startswith("YOUR_"):
        camps.append((CONFIG["extra_campaign_label"], CONFIG["extra_campaign_id"]))
    return camps


# ====================================================================
# 결과 수집 및 출력 유틸
# ====================================================================
_results: list[dict] = []

def _record(label: str, status: str, notes: list[str] = None, raw=None):
    _results.append({
        "label":  label,
        "status": status,
        "notes":  notes or [],
        "raw":    raw,
    })

def ok(label: str, notes: list[str] = None, raw=None):
    _record(label, "✅ OK", notes, raw)

def warn(label: str, notes: list[str] = None, raw=None):
    _record(label, "⚠️  WARN", notes, raw)

def fail(label: str, notes: list[str] = None, raw=None):
    _record(label, "❌ FAIL", notes, raw)

def print_summary():
    print("\n" + "=" * 72)
    print("  META API 검증 결과")
    print("=" * 72)
    n_ok   = sum(1 for r in _results if r["status"] == "✅ OK")
    n_warn = sum(1 for r in _results if r["status"] == "⚠️  WARN")
    n_fail = sum(1 for r in _results if r["status"] == "❌ FAIL")
    print(f"  총 {len(_results)}개 항목   ✅ {n_ok}   ⚠️  {n_warn}   ❌ {n_fail}")
    print("-" * 72)
    for r in _results:
        print(f"  {r['status']}  {r['label']}")
        for n in r["notes"]:
            print(f"           → {n}")
    print("=" * 72)


# ====================================================================
# Graph API GET 래퍼 (1회 재시도)
# ====================================================================
def graph_get(path: str, params: dict = None) -> dict | None:
    """
    성공 시 dict 반환. 오류 시 None 반환 + 오류 내용 출력.
    검증 스크립트이므로 실패해도 계속 진행.
    """
    p = {"access_token": CONFIG["access_token"], **(params or {})}
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=p, timeout=30)
        data = r.json()
    except Exception as e:
        print(f"  [네트워크 오류] {path}: {e}")
        return None

    if "error" in data:
        err = data["error"]
        # Rate limit 시 1회만 재시도
        if err.get("code") in (4, 17, 32):
            print(f"  [Rate limit] {path} — 10s 후 재시도...")
            time.sleep(10)
            try:
                r = requests.get(url, params=p, timeout=30)
                data = r.json()
            except Exception as e:
                print(f"  [재시도 실패] {path}: {e}")
                return None
            if "error" in data:
                return None
        else:
            return None  # 오류 내용은 호출부에서 기록

    return data


def graph_get_verbose(path: str, params: dict = None) -> tuple[dict | None, str | None]:
    """raw 오류 메시지도 함께 반환."""
    p = {"access_token": CONFIG["access_token"], **(params or {})}
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=p, timeout=30)
        data = r.json()
    except Exception as e:
        return None, str(e)

    if "error" in data:
        err = data["error"]
        msg = f"code={err.get('code')} type={err.get('type')} msg={err.get('message','')[:120]}"
        if err.get("code") in (4, 17, 32):
            print(f"  [Rate limit] {path} — 10s 후 재시도...")
            time.sleep(10)
            try:
                r = requests.get(url, params=p, timeout=30)
                data = r.json()
            except Exception as e:
                return None, str(e)
            if "error" in data:
                err2 = data["error"]
                return None, f"code={err2.get('code')} msg={err2.get('message','')[:120]}"
            return data, None
        return None, msg

    return data, None


def first_item(data: dict) -> dict | None:
    """data['data'][0] 안전하게 꺼내기."""
    if not data:
        return None
    items = data.get("data", [])
    return items[0] if items else None


# ====================================================================
# §0. 사전 검사: 토큰 유효성 · 권한 · 토큰 만료일
# ====================================================================
def check_token():
    print("\n── §0. 토큰 / 권한 검증 ──────────────────────────────────────────")

    # 0-1. 토큰 기본 유효성
    data, err = graph_get_verbose("me", {"fields": "id,name"})
    if data:
        ok("토큰 유효성", [f"id={data.get('id')}  name={data.get('name')}"])
    else:
        fail("토큰 유효성", [err or "알 수 없는 오류"])
        print("  ⛔ 토큰이 유효하지 않아 이후 검증이 의미 없을 수 있습니다.")
        return

    # 0-2. 토큰 만료일 (debug_token)
    dbg, err2 = graph_get_verbose(
        "debug_token",
        {"input_token": CONFIG["access_token"]},
    )
    if dbg:
        ddata = dbg.get("data", {})
        exp_at = ddata.get("expires_at", 0)
        is_valid = ddata.get("is_valid", False)
        if exp_at == 0:
            ok("토큰 만료일", ["장기(영구) 토큰 — 만료 없음"])
        else:
            exp_dt = datetime.fromtimestamp(exp_at).strftime("%Y-%m-%d %H:%M:%S")
            remaining = (datetime.fromtimestamp(exp_at) - datetime.now()).days
            if remaining < 7:
                warn("토큰 만료일", [f"{exp_dt} (D-{remaining}) — 곧 만료됩니다!"])
            else:
                ok("토큰 만료일", [f"{exp_dt} (D-{remaining})"])
        if not is_valid:
            fail("토큰 is_valid", ["Meta가 토큰을 유효하지 않다고 응답함"])
    else:
        warn("토큰 만료일 확인", [f"debug_token 접근 불가 (System User 토큰일 수 있음): {err2}"])

    # 0-3. 필수 권한 확인
    perm_data, perr = graph_get_verbose("me/permissions")
    if perm_data:
        granted = {p["permission"] for p in perm_data.get("data", []) if p.get("status") == "granted"}
        required = {
            "ads_read", "ads_management", "read_insights",
            "instagram_basic", "instagram_manage_insights",
            "business_management",
        }
        missing = required - granted
        if missing:
            warn("필수 권한", [f"누락: {sorted(missing)}", f"보유: {sorted(granted & required)}"])
        else:
            ok("필수 권한", [f"필요 권한 모두 보유: {sorted(required)}"])
    else:
        warn("권한 확인", [f"me/permissions 접근 불가: {perr}"])


# ====================================================================
# §1. campaigns 테이블
# ====================================================================
def check_campaigns():
    print("\n── §1. campaigns 테이블 ──────────────────────────────────────────")
    FIELDS = "name,objective,status,created_time,updated_time"

    for label, cid in campaign_list():
        data, err = graph_get_verbose(cid, {"fields": FIELDS})
        if not data:
            fail(f"[campaigns] {label} ({cid})", [err or "응답 없음"])
            continue
        missing = [f for f in ["name", "objective", "status"] if f not in data]
        if missing:
            warn(f"[campaigns] {label}", [f"누락 필드: {missing}"], data)
        else:
            ok(f"[campaigns] {label}",
               [f"name={data['name']!r}  objective={data.get('objective')}  status={data.get('status')}"],
               data)


# ====================================================================
# §2. ad_sets 테이블
# ====================================================================
def check_ad_sets():
    print("\n── §2. ad_sets 테이블 ───────────────────────────────────────────")
    FIELDS = "name,optimization_goal,billing_event,status,effective_status,targeting,created_time,updated_time"

    for label, cid in campaign_list():
        data, err = graph_get_verbose(f"{cid}/adsets", {"fields": FIELDS, "limit": 5})
        if not data:
            fail(f"[ad_sets] {label}", [err or "응답 없음"])
            continue

        items = data.get("data", [])
        if not items:
            warn(f"[ad_sets] {label}", ["광고세트가 0개 — 캠페인에 광고세트가 없습니다"])
            continue

        adset = items[0]
        REQUIRED = ["name", "optimization_goal", "billing_event", "status", "effective_status", "targeting"]
        missing = [f for f in REQUIRED if f not in adset]
        notes = [f"총 {len(items)}개 중 첫 번째 확인"]

        if missing:
            warn(f"[ad_sets] {label}", [f"누락 필드: {missing}"] + notes, adset)
        else:
            # targeting_spec 구조 힌트
            tgt_keys = list((adset.get("targeting") or {}).keys())
            ok(f"[ad_sets] {label}",
               [f"optimization_goal={adset.get('optimization_goal')}  "
                f"billing_event={adset.get('billing_event')}",
                f"targeting 최상위 키: {tgt_keys}"] + notes,
               adset)


# ====================================================================
# §3. ads 테이블 (body 포함)
# ====================================================================
def check_ads():
    print("\n── §3. ads 테이블 ───────────────────────────────────────────────")
    # body 는 adcreatives.body 에 있음 (광고 유형마다 없을 수 있음)
    FIELDS = "name,status,created_time,updated_time,adcreatives{body,object_story_spec}"

    for label, cid in campaign_list():
        data, err = graph_get_verbose(f"{cid}/ads", {"fields": FIELDS, "limit": 5})
        if not data:
            fail(f"[ads] {label}", [err or "응답 없음"])
            continue

        items = data.get("data", [])
        if not items:
            warn(f"[ads] {label}", ["광고가 0개"])
            continue

        ad = items[0]
        missing_base = [f for f in ["name", "status"] if f not in ad]
        if missing_base:
            warn(f"[ads] {label} 기본 필드", [f"누락: {missing_base}"], ad)
        else:
            ok(f"[ads] {label} 기본 필드 (name, status)", [f"총 {len(items)}개 확인"])

        # body 확인
        creatives = ad.get("adcreatives", {}).get("data", [])
        if creatives and creatives[0].get("body"):
            ok(f"[ads] {label} → adcreatives.body", [f"body={creatives[0]['body'][:60]!r}"])
        else:
            warn(f"[ads] {label} → adcreatives.body",
                 ["body 없음 — 광고 유형(이미지/영상/DPA)에 따라 body가 없을 수 있음"])


# ====================================================================
# §4. ad_performance_daily 테이블
# ====================================================================
# 지표 분류:
#  A) 직접 필드 (insights 응답 최상위)
#  B) actions[] 에서 action_type 으로 추출
#  C) 비디오 전용 필드

_DIRECT_FIELDS = [
    "reach", "impressions", "clicks", "ctr", "inline_post_engagement",
    "spend", "frequency", "cpc", "cpm",
    # purchase_roas는 breakdown 셀에 구매가 있을 때만 반환됨.
    # items[0] 으로 확인하면 오판 위험 → 캠페인 집계 레벨(diag_data)에서 별도 확인.
]
_ACTION_MAP = {
    # DB 컬럼명 : Meta action_type 값
    # 웹사이트 픽셀 전환 이벤트 → offsite_conversion.fb_pixel_* 형식
    "link_clicks":                    "link_click",
    "website_landing_page_views":     "landing_page_view",
    "add_to_cart":                    "offsite_conversion.fb_pixel_add_to_cart",
    "purchases":                      "offsite_conversion.fb_pixel_purchase",
    "view_content":                   "offsite_conversion.fb_pixel_view_content",
    "initiate_checkout":              "offsite_conversion.fb_pixel_initiate_checkout",
    "complete_registration":          "offsite_conversion.fb_pixel_complete_registration",
    "post_reactions":                 "post_reaction",
    "comments":                       "comment",
    "post_saves":                     "onsite_conversion.post_save",
    # instagram_profile_visits / follows → actions 배열에 미포함.
    # 별도 접근법으로 check_ad_performance 내 §B-2 에서 검증.
}
_VIDEO_FIELDS = [
    ("video_views",            "video_30_sec_watched_actions"),
    ("video_p25_watched",      "video_p25_watched_actions"),
    ("video_p50_watched",      "video_p50_watched_actions"),
    ("video_p75_watched",      "video_p75_watched_actions"),
    ("video_p100_watched",     "video_p100_watched_actions"),
    ("video_thruplay_watched", "video_thruplay_watched_actions"),
]

def check_ad_performance():
    print("\n── §4. ad_performance_daily 테이블 ──────────────────────────────")

    # 요청할 필드 문자열 구성
    insight_fields = ",".join(
        _DIRECT_FIELDS
        + ["actions", "action_values"]
        + [api_f for _, api_f in _VIDEO_FIELDS]
    )

    for label, cid in campaign_list():
        data, err = graph_get_verbose(
            f"{cid}/insights",
            {
                "fields":       insight_fields,
                "breakdowns":   "age,gender",
                "level":        "ad",
                "time_range":   json.dumps({"since": DATE_START, "until": DATE_END}),
                "time_increment": 1,
                "limit":        5,
            },
        )
        if not data:
            fail(f"[ad_performance] {label} insights", [err or "응답 없음"])
            continue

        items = data.get("data", [])
        if not items:
            warn(f"[ad_performance] {label}", ["기간 내 성과 데이터 없음 (날짜 범위 확인)"])
            continue

        row = items[0]

        # --- A) 직접 필드 ---
        miss_expected = [f for f in _DIRECT_FIELDS if f not in row]
        if miss_expected:
            warn(f"[ad_performance] {label} 직접 지표", [f"누락: {miss_expected}"])
        else:
            ok(f"[ad_performance] {label} 직접 지표 (reach/impressions/spend/cpm 등)")

        # age / gender breakdown 확인
        if "age" in row and "gender" in row:
            ok(f"[ad_performance] {label} age/gender 세분화",
               [f"age={row['age']}  gender={row['gender']}"])
        else:
            warn(f"[ad_performance] {label} age/gender 세분화",
                 [f"breakdown 키 없음 — row keys: {list(row.keys())}"])

        # --- B) actions 기반 지표 ---
        # breakdown=age,gender + limit=5 샘플은 coverage가 낮아 누락 오판 가능.
        # 캠페인 레벨 집계(breakdown 없음)로 action_type 전체 목록 + purchase_roas 를 함께 확인.
        diag_data, _ = graph_get_verbose(
            f"{cid}/insights",
            {
                "fields":     "actions,purchase_roas",
                "level":      "campaign",
                "time_range": json.dumps({"since": DATE_START, "until": DATE_END}),
                "limit":      1,
            },
        )
        diag_rows = (diag_data or {}).get("data", [])
        campaign_row = diag_rows[0] if diag_rows else {}

        # purchase_roas — 캠페인 집계 행에서 확인 (breakdown 셀에 구매 없으면 미노출되므로 여기서만 신뢰)
        if "purchase_roas" in campaign_row:
            ok(f"[ad_performance] {label} purchase_roas",
               [f"캠페인 집계 기준 값={campaign_row['purchase_roas']}"])
        elif label == "구매전환 캠페인":
            warn(f"[ad_performance] {label} purchase_roas",
                 ["구매전환 캠페인인데 purchase_roas 없음 — 조회 기간 내 구매 성과 없거나 ROAS 설정 확인 필요"])
        else:
            ok(f"[ad_performance] {label} purchase_roas",
               ["구매전환 캠페인이 아님 — 해당 없음 (정상)"])

        actions_campaign = {
            a["action_type"]
            for row_ in diag_rows
            for a in row_.get("actions", [])
        }
        # breakdown 샘플에서도 합산 (보조)
        actions_breakdown = {
            a["action_type"]
            for row_ in items
            for a in row_.get("actions", [])
        }
        actions_present = actions_campaign | actions_breakdown

        # 진단용: 캠페인 레벨에서 실제 수집된 action_type 목록 출력
        ok(f"[ad_performance] {label} 발견된 action_type 목록 (캠페인 집계 기준)",
           sorted(actions_present))

        # 캠페인 objective 조회 — action WARN 메시지 문맥 제공용
        obj_data, _ = graph_get_verbose(cid, {"fields": "objective"})
        objective = (obj_data or {}).get("objective", "")

        # 픽셀 전환 이벤트 컬럼 — OUTCOME_SALES 이외 캠페인에서는 미발생이 정상
        _PIXEL_COLS = {
            "add_to_cart", "purchases", "view_content",
            "initiate_checkout", "complete_registration",
        }

        for db_col, action_type in _ACTION_MAP.items():
            if action_type in actions_present:
                ok(f"[ad_performance] {label} actions[{db_col}]")
            else:
                if db_col in _PIXEL_COLS and objective and objective != "OUTCOME_SALES":
                    warn(f"[ad_performance] {label} actions[{db_col}]",
                         [f"action_type='{action_type}' 미발견",
                          f"→ 원인: objective={objective} — 전환(구매) 캠페인이 아니므로 픽셀 전환 이벤트 미발생 (정상)"])
                else:
                    warn(f"[ad_performance] {label} actions[{db_col}]",
                         [f"action_type='{action_type}' 캠페인 전체 기간 미발견",
                          "→ 원인: 해당 기간 실제 미발생 또는 action_type 명칭 불일치 확인 필요"])

        # --- B-2) instagram_profile_visits / follows 전용 검증 ---
        # actions 배열에 포함되지 않음 → 직접 필드(direct field) 방식으로만 검증.
        # ※ results 폴백은 캠페인 목적 지표(구매/프로필방문)를 반환하므로 follows 검증에 부적합 — 제거.

        # instagram_profile_visits: 직접 필드로 수집 가능 (검증 완료)
        igpv_data, _ = graph_get_verbose(
            f"{cid}/insights",
            {
                "fields":     "instagram_profile_visits",
                "level":      "campaign",
                "time_range": json.dumps({"since": DATE_START, "until": DATE_END}),
                "limit":      1,
            },
        )
        igpv_rows = (igpv_data or {}).get("data", [])
        if igpv_rows and "instagram_profile_visits" in igpv_rows[0]:
            ok(f"[ad_performance] {label} instagram_profile_visits",
               [f"직접 필드로 수집 가능  값={igpv_rows[0]['instagram_profile_visits']}"])
        else:
            # actions 배열 fallback
            at_candidates = ["instagram_profile_visit",
                             "onsite_conversion.instagram_profile_visit", "profile_visit"]
            matched = next((at for at in at_candidates if at in actions_present), None)
            if matched:
                ok(f"[ad_performance] {label} instagram_profile_visits",
                   [f"actions[action_type='{matched}'] 로 수집 가능"])
            else:
                warn(f"[ad_performance] {label} instagram_profile_visits",
                     ["직접 필드 및 actions 모두에서 미발견"])

        # follows: 직접 필드 후보 순차 시도
        # results 필드는 캠페인 목적 지표를 반환하므로 follows 검증에 사용하지 않음
        _follows_direct_candidates = ["follows", "instagram_follows", "follow_count"]
        _follows_action_candidates = ["follow", "onsite_conversion.follow", "instagram_follow"]
        follows_found = False
        follows_method = None

        # 방법 1: actions 배열
        for at in _follows_action_candidates:
            if at in actions_present:
                follows_method = f"actions[action_type='{at}']"
                follows_found = True
                break

        # 방법 2: 직접 필드 후보들
        if not follows_found:
            for df in _follows_direct_candidates:
                df_data, _ = graph_get_verbose(
                    f"{cid}/insights",
                    {
                        "fields":     df,
                        "level":      "campaign",
                        "time_range": json.dumps({"since": DATE_START, "until": DATE_END}),
                        "limit":      1,
                    },
                )
                df_rows = (df_data or {}).get("data", [])
                if df_rows and df in df_rows[0]:
                    follows_method = f"직접 필드 '{df}'  값={df_rows[0][df]}"
                    follows_found = True
                    break

        if follows_found:
            ok(f"[ad_performance] {label} follows", [f"{follows_method} 로 수집 가능"])
        else:
            warn(f"[ad_performance] {label} follows",
                 ["직접 필드·actions 모두 미발견 (모든 캠페인 동일)",
                  f"→ 시도 action_type: {_follows_action_candidates}",
                  f"→ 시도 직접 필드: {_follows_direct_candidates}",
                  "→ 원인: Meta Graph API v21.0에서 광고 단위 Instagram 팔로우를 외부에 노출하지 않음",
                  "   Ads Manager 내부 지표로만 집계되며 Graph API 응답에 포함되지 않음",
                  "→ 결론: ad_performance_daily.follows 컬럼 DB에서 제거 권장",
                  "   (계정 전체 순팔로우는 §7 ig_user_id/insights follows_and_unfollows 로 별도 수집 가능)"])

        # --- C) 비디오 지표 ---
        # 비디오 소재 존재 여부 판단:
        #   - actions 집계에 video_view 포함 → 비디오 소재 있음
        #   - 다른 구간 지표(p25/p50 등)가 row에 존재해도 비디오 소재 있음
        has_video_in_actions = "video_view" in actions_present
        present_video_fields = {api_f for _, api_f in _VIDEO_FIELDS if api_f in row}
        has_video = has_video_in_actions or bool(present_video_fields)

        for db_col, api_field in _VIDEO_FIELDS:
            if api_field in row:
                ok(f"[ad_performance] {label} {db_col} ({api_field})")
            elif has_video:
                # 비디오 소재는 있으나 해당 구간 지표 미집계
                if db_col == "video_views":  # video_30_sec_watched_actions
                    warn(f"[ad_performance] {label} {db_col}",
                         ["video_30_sec_watched_actions 없음",
                          "→ 원인: 영상 길이가 30초 미만인 소재에서는 이 지표가 집계되지 않음",
                          f"   (다른 구간 지표 존재: {sorted(present_video_fields) or '없음'} → 영상 소재는 확인됨)"])
                elif db_col == "video_p100_watched":
                    warn(f"[ad_performance] {label} {db_col}",
                         ["100% 완시청자 없음",
                          "→ 원인: 광고 중간 이탈로 인해 흔히 발생 (비정상 아님)"])
                else:
                    warn(f"[ad_performance] {label} {db_col}",
                         [f"해당 시청 구간({db_col}) 달성자 없음",
                          "→ 원인: 영상이 짧거나 해당 구간 도달 전 이탈로 추정"])
            else:
                warn(f"[ad_performance] {label} {db_col}",
                     ["→ 원인: 비디오 광고 없음 또는 해당 기간 내 영상 시청 없음 (이미지/텍스트 소재 캠페인)"])


# ====================================================================
# §5. ig_organic_insights 테이블
# ====================================================================
def check_ig_organic():
    print("\n── §5. ig_organic_insights 테이블 ───────────────────────────────")
    ig_id = CONFIG["ig_user_id"]

    # organic_views: media_product_type 세분화에서 non-AD 합산으로 구성
    # IG Insights는 since/until 간격 최대 30일 → IG_DATE_START 사용
    data, err = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "views",
            "metric_type":  "total_value",
            "period":       "day",
            "breakdown":    "media_product_type",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
        },
    )
    if data:
        ok("[ig_organic_insights] views (media_product_type 세분화)",
           ["organic_views = 전체 views 에서 AD 제외 합산으로 구성 가능"])
    else:
        fail("[ig_organic_insights] views", [err or "응답 없음"])

    # 일별 시계열 — metric_type=total_value 필수
    data2, err2 = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "views",
            "metric_type":  "total_value",
            "period":       "day",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
        },
    )
    if data2:
        ok("[ig_organic_insights] views (period=day, 일별 시계열)")
    else:
        warn("[ig_organic_insights] views 일별", [err2 or "응답 없음"])


# ====================================================================
# §6. ig_insights_demographics 테이블
# ====================================================================
def check_ig_demographics():
    print("\n── §6. ig_insights_demographics 테이블 ──────────────────────────")
    ig_id = CONFIG["ig_user_id"]

    # 팔로워 인구통계 (followers by age, gender)
    data, err = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "follower_demographics",
            "period":       "lifetime",
            "metric_type":  "total_value",
            "breakdown":    "age,gender",
        },
    )
    if data:
        # 응답 구조 힌트
        dval = (data.get("data") or [{}])[0]
        ok("[ig_demographics] followers (age/gender 세분화)",
           [f"응답 최상위 키: {list(dval.keys())}"])
    else:
        fail("[ig_demographics] follower_demographics", [err or "응답 없음"])

    # 참여 오디언스 인구통계 (engaged_audience by age, gender)
    # timeframe 지원값이 API 버전마다 달라지므로 순서대로 시도
    _TIMEFRAMES = ["this_month", "last_14_days", "this_week", "last_90_days", "prev_month"]
    data2 = None
    used_tf = None
    last_err = None
    for tf in _TIMEFRAMES:
        data2, last_err = graph_get_verbose(
            f"{ig_id}/insights",
            {
                "metric":       "engaged_audience_demographics",
                "period":       "lifetime",
                "metric_type":  "total_value",
                "breakdown":    "age,gender",
                "timeframe":    tf,
            },
        )
        if data2:
            used_tf = tf
            break

    if data2:
        ok("[ig_demographics] engaged_audience (age/gender 세분화)",
           [f"사용된 timeframe='{used_tf}'"])
    else:
        fail("[ig_demographics] engaged_audience_demographics",
             [f"모든 timeframe 시도 실패 ({_TIMEFRAMES})",
              last_err or "응답 없음"])


# ====================================================================
# §7. ig_insights_total 테이블
# ====================================================================
def check_ig_total():
    print("\n── §7. ig_insights_total 테이블 ─────────────────────────────────")
    ig_id = CONFIG["ig_user_id"]

    # IG Insights — metric_type=total_value 필수, 30일 제한 적용
    def _check(label: str, metric: str, extra_params: dict = None):
        params = {
            "metric":       metric,
            "metric_type":  "total_value",
            "period":       "day",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
            **(extra_params or {}),
        }
        d, e = graph_get_verbose(f"{ig_id}/insights", params)
        if d:
            ok(label)
        else:
            fail(label, [e or "응답 없음"])

    # 단순 합계 지표
    SIMPLE_METRICS = [
        ("total_interactions",  "total_interactions"),
        ("likes",               "likes"),
        ("comments",            "comments"),
        ("shares",              "shares"),
        ("saves",               "saves"),
        ("replies",             "replies"),
        ("profile_links_taps",  "profile_links_taps"),
    ]
    for db_col, metric in SIMPLE_METRICS:
        _check(f"[ig_total] {db_col}", metric)

    # follows / unfollows → follows_and_unfollows (metric_type=total_value 필수)
    data_fu, err_fu = graph_get_verbose(
        f"{ig_id}/insights",
        {"metric": "follows_and_unfollows", "metric_type": "total_value",
         "period": "day", "since": IG_DATE_START, "until": IG_DATE_END},
    )
    if data_fu:
        ok("[ig_total] follows / unfollows (follows_and_unfollows)",
           ["응답 내 breakdown_type 으로 follows/unfollows 구분"])
    else:
        fail("[ig_total] follows_and_unfollows", [err_fu or "응답 없음"])

    # reposts — metric_type=total_value 추가 후에도 미지원이면 스키마 제거 권장
    data_rp, err_rp = graph_get_verbose(
        f"{ig_id}/insights",
        {"metric": "reposts", "metric_type": "total_value",
         "period": "day", "since": IG_DATE_START, "until": IG_DATE_END},
    )
    if data_rp:
        ok("[ig_total] reposts")
    else:
        warn("[ig_total] reposts",
             [f"응답 없음 ({err_rp}) — API 미지원 metric, 스키마에서 제거 검토"])

    # reach — 세분화 없이 전체 (30일 제한 적용)
    _check("[ig_total] total_reach", "reach")

    # reach breakdown by media_product_type (reach_ad / reach_post / reach_reel / reach_story)
    data_rmt, err_rmt = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "reach",
            "metric_type":  "total_value",
            "period":       "day",
            "breakdown":    "media_product_type",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
        },
    )
    if data_rmt:
        ok("[ig_total] reach_ad / reach_post / reach_carousel / reach_reel / reach_story",
           ["media_product_type 세분화로 수집 가능"])
    else:
        fail("[ig_total] reach by media_product_type", [err_rmt or "응답 없음"])

    # reach breakdown by follow_type (reach_follower / reach_non_follower)
    data_rft, err_rft = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "reach",
            "metric_type":  "total_value",
            "period":       "day",
            "breakdown":    "follow_type",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
        },
    )
    if data_rft:
        ok("[ig_total] reach_follower / reach_non_follower",
           ["follow_type 세분화로 수집 가능"])
    else:
        fail("[ig_total] reach by follow_type", [err_rft or "응답 없음"])

    # views breakdown by media_product_type (views_ad / views_post / views_reel / views_story)
    data_vmt, err_vmt = graph_get_verbose(
        f"{ig_id}/insights",
        {
            "metric":       "views",
            "metric_type":  "total_value",
            "period":       "day",
            "breakdown":    "media_product_type",
            "since":        IG_DATE_START,
            "until":        IG_DATE_END,
        },
    )
    if data_vmt:
        ok("[ig_total] views_ad / views_post / views_carousel / views_reel / views_story",
           ["media_product_type 세분화로 수집 가능"])
    else:
        fail("[ig_total] views by media_product_type", [err_vmt or "응답 없음"])


# ====================================================================
# §8. ig_contents 테이블 (릴스 / 캐러셀 기본 정보)
# ====================================================================
def check_ig_contents():
    print("\n── §8. ig_contents 테이블 ───────────────────────────────────────")
    FIELDS = "caption,media_type,permalink,timestamp"

    for media_label, media_id in [
        ("릴스",    CONFIG["ig_reels_media_id"]),
        ("캐러셀",  CONFIG["ig_carousel_media_id"]),
    ]:
        data, err = graph_get_verbose(media_id, {"fields": FIELDS})
        if not data:
            fail(f"[ig_contents] {media_label} ({media_id})", [err or "응답 없음"])
            continue
        REQUIRED = ["media_type", "permalink", "timestamp"]
        missing = [f for f in REQUIRED if f not in data]
        if missing:
            warn(f"[ig_contents] {media_label} 기본 필드", [f"누락: {missing}"], data)
        else:
            ok(f"[ig_contents] {media_label} (caption/media_type/permalink/timestamp)",
               [f"media_type={data.get('media_type')}",
                f"permalink={data.get('permalink')}",
                f"caption 있음: {bool(data.get('caption'))}"])

    # 캐러셀 하위 이미지 확인 (children)
    data_ch, err_ch = graph_get_verbose(
        f"{CONFIG['ig_carousel_media_id']}/children",
        {"fields": "id,media_type,permalink"},
    )
    if data_ch:
        children = data_ch.get("data", [])
        ok(f"[ig_contents] 캐러셀 하위 children", [f"{len(children)}개 슬라이드 확인"])
    else:
        warn("[ig_contents] 캐러셀 children", [err_ch or "응답 없음"])


# ====================================================================
# §9. ig_contents_insights 테이블
# ====================================================================
def check_ig_contents_insights():
    print("\n── §9. ig_contents_insights 테이블 ──────────────────────────────")

    # ------------------------------------------------------------------
    # 9-A. 릴스
    # clips_replays_count        → v22.0+ deprecated, 제거
    # follows/profile_visits/profile_activity → 릴스(VIDEO) API 미지원, 제거
    # ------------------------------------------------------------------
    REEL_BASE = [
        "reach", "likes", "comments", "shares", "saved",
        "total_interactions", "views",
    ]
    REEL_ONLY = [
        "ig_reels_avg_watch_time",        # 평균 시청 시간 (ms) → 앱의 "평균 시청 시간"
        "ig_reels_video_view_total_time", # 총 시청 시간 (ms)  → 앱의 "시청 시간"
    ]

    data_r, err_r = graph_get_verbose(
        f"{CONFIG['ig_reels_media_id']}/insights",
        {"metric": ",".join(REEL_BASE + REEL_ONLY)},
    )
    if data_r:
        fetched_r = {i["name"]: i for i in data_r.get("data", [])}
        fetched_names = set(fetched_r)

        def _val(item: dict) -> str:
            """insights 응답에서 값 추출 (values[0] 또는 total_value)."""
            vals = item.get("values", [])
            if vals:
                return str(vals[0].get("value", "?"))
            return str(item.get("total_value", "?"))

        # 기본 지표 확인
        miss_base = [m for m in REEL_BASE if m not in fetched_names]
        if miss_base:
            warn("[ig_contents_insights] 릴스 기본 지표", [f"누락: {miss_base}"])
        else:
            ok("[ig_contents_insights] 릴스 기본 지표",
               [f"reach={_val(fetched_r['reach'])}  "
                f"views={_val(fetched_r['views'])}  "
                f"likes={_val(fetched_r['likes'])}  "
                f"comments={_val(fetched_r['comments'])}  "
                f"shares={_val(fetched_r['shares'])}  "
                f"saved={_val(fetched_r['saved'])}  "
                f"total_interactions={_val(fetched_r['total_interactions'])}"])

        # 릴스 전용 지표 확인
        for metric in REEL_ONLY:
            if metric in fetched_names:
                raw_ms = _val(fetched_r[metric])
                # ms → 시간/분/초 변환 (가독성)
                try:
                    sec = int(raw_ms) // 1000
                    readable = f"{sec // 3600}h {(sec % 3600) // 60}m {sec % 60}s"
                except (ValueError, TypeError):
                    readable = raw_ms
                ok(f"[ig_contents_insights] 릴스 전용 → {metric}",
                   [f"raw={raw_ms}ms  ({readable})"])
            else:
                warn(f"[ig_contents_insights] 릴스 전용 → {metric}", ["응답에 없음"])

        # follows / profile_visits / profile_activity — 미지원 명시
        warn("[ig_contents_insights] 릴스 → follows / profile_visits / profile_activity",
             ["릴스(VIDEO) 타입에서 Media Insights API 미지원 (API 정책)",
              "→ DB 컬럼 NULL 허용 필요",
              "→ 팔로우는 ig_user_id/insights follows_and_unfollows 로 계정 전체 수집 가능"])
    else:
        fail("[ig_contents_insights] 릴스", [err_r or "응답 없음"])

    # ------------------------------------------------------------------
    # 9-B. 캐러셀 (CAROUSEL_ALBUM)
    # 피드/캐러셀은 follows / profile_visits / profile_activity 지원 여부 확인
    # ------------------------------------------------------------------
    CAROUSEL_BASE = [
        "reach", "likes", "comments", "shares", "saved",
        "total_interactions", "views",
    ]
    CAROUSEL_EXTRA = [
        "follows", "profile_visits", "profile_activity",
    ]

    data_c, err_c = graph_get_verbose(
        f"{CONFIG['ig_carousel_media_id']}/insights",
        {"metric": ",".join(CAROUSEL_BASE + CAROUSEL_EXTRA)},
    )
    if data_c:
        fetched_c = {i["name"]: i for i in data_c.get("data", [])}
        fetched_names_c = set(fetched_c)

        def _val_c(item: dict) -> str:
            vals = item.get("values", [])
            if vals:
                return str(vals[0].get("value", "?"))
            return str(item.get("total_value", "?"))

        # 기본 지표
        miss_base_c = [m for m in CAROUSEL_BASE if m not in fetched_names_c]
        if miss_base_c:
            warn("[ig_contents_insights] 캐러셀 기본 지표", [f"누락: {miss_base_c}"])
        else:
            ok("[ig_contents_insights] 캐러셀 기본 지표",
               [f"reach={_val_c(fetched_c['reach'])}  "
                f"views={_val_c(fetched_c['views'])}  "
                f"likes={_val_c(fetched_c['likes'])}  "
                f"comments={_val_c(fetched_c['comments'])}  "
                f"shares={_val_c(fetched_c['shares'])}  "
                f"saved={_val_c(fetched_c['saved'])}  "
                f"total_interactions={_val_c(fetched_c['total_interactions'])}"])

        # follows / profile_visits / profile_activity 지원 여부
        for metric in CAROUSEL_EXTRA:
            if metric in fetched_names_c:
                ok(f"[ig_contents_insights] 캐러셀 → {metric}",
                   [f"값={_val_c(fetched_c[metric])}"])
            else:
                warn(f"[ig_contents_insights] 캐러셀 → {metric}",
                     ["응답에 없음 — 캐러셀도 미지원, DB NULL 허용 필요"])
    else:
        fail("[ig_contents_insights] 캐러셀", [err_c or "응답 없음"])


# ====================================================================
# §10. 보완 제안 항목 체크
# ====================================================================
def check_extras():
    print("\n── §10. 추가 점검 항목 ──────────────────────────────────────────")

    # 10-1. 광고 계정 ID 확인 (ad_accounts 테이블 연결 검증)
    #       캠페인에서 account_id 를 역추적해 ad_account 테이블 연동 가능 여부 확인
    for label, cid in campaign_list():
        data, err = graph_get_verbose(cid, {"fields": "account_id"})
        if data and data.get("account_id"):
            ok(f"[extras] {label} → account_id 역추적",
               [f"account_id={data['account_id']} (ad_accounts FK 연결 가능)"])
        else:
            warn(f"[extras] {label} → account_id", [err or "account_id 없음"])

    # 10-2. IG 계정 ↔ 광고계정 연결 확인
    ig_id = CONFIG["ig_user_id"]
    data_ig, err_ig = graph_get_verbose(ig_id, {"fields": "id,username,followers_count"})
    if data_ig:
        ok("[extras] IG 계정 기본 정보 접근",
           [f"username={data_ig.get('username')}  followers={data_ig.get('followers_count')}"])
    else:
        fail("[extras] IG 계정 접근", [err_ig or "응답 없음",
             "ig_user_id 가 잘못됐거나 해당 IG 계정에 접근 권한이 없습니다"])

    # 10-3. ad_keywords 용 — ad body 에서 키워드 추출 가능 여부 (text 존재 확인)
    for label, cid in campaign_list():
        data, err = graph_get_verbose(
            f"{cid}/ads",
            {"fields": "name,adcreatives{body,title,description,link_description}", "limit": 3},
        )
        if data:
            ads = data.get("data", [])
            has_text = any(
                any([
                    (cr.get("body") or cr.get("title") or cr.get("description"))
                    for cr in (ad.get("adcreatives") or {}).get("data", [])
                ])
                for ad in ads
            )
            if has_text:
                ok(f"[extras] {label} ad_keywords 원본(body/title) 수집 가능")
            else:
                warn(f"[extras] {label} ad_keywords", ["body/title 텍스트 없음 — DPA 또는 동적 소재일 가능성"])
        else:
            warn(f"[extras] {label} ad body 확인", [err or "응답 없음"])

    # 10-4. API 버전 최신 여부 안내
    warn("[extras] API 버전 확인",
         [f"현재 GRAPH_API_VERSION={GRAPH_API_VERSION}",
          "Meta는 약 2년마다 구버전 deprecated — "
          "https://developers.facebook.com/docs/graph-api/changelog 에서 최신 버전 확인 권장"])

    # 10-5. 페이지네이션 대응 안내
    ok("[extras] 페이지네이션",
       ["대용량 캠페인은 adsets/ads 결과가 페이지네이션됨",
        "paging.next 처리 로직 필수 (lambda_meta_sync.py get_all_pages 참고)"])


# ====================================================================
# main
# ====================================================================
if __name__ == "__main__":
    # 필수 키는 채워져야 함 / 선택 키(extra_*)는 YOUR_ 그대로여도 건너뜀
    _OPTIONAL_KEYS = {"extra_campaign_id", "extra_campaign_label"}
    unfilled = [
        k for k, v in CONFIG.items()
        if k != "access_token"
        and k not in _OPTIONAL_KEYS
        and isinstance(v, str) and v.startswith("YOUR_")
    ]
    if unfilled:
        print("=" * 60)
        print("  ⛔ CONFIG 에 값이 채워지지 않은 항목이 있습니다:")
        for k in unfilled:
            print(f"    - {k}")
        print("=" * 60)
        raise SystemExit(1)

    # 추가 캠페인 활성 여부
    _extra_active = not CONFIG["extra_campaign_id"].startswith("YOUR_")

    print(f"\n{'='*72}")
    print(f"  Meta API 검증 시작  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"  조회 기간: {DATE_START} ~ {DATE_END}")
    print(f"  API 버전: {GRAPH_API_VERSION}")
    print(f"{'='*72}")

    check_token()
    check_campaigns()
    check_ad_sets()
    check_ads()
    check_ad_performance()
    check_ig_organic()
    check_ig_demographics()
    check_ig_total()
    check_ig_contents()
    check_ig_contents_insights()
    check_extras()

    print_summary()
