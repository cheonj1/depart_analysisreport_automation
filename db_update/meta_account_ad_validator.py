"""
meta_account_ad_validator.py
────────────────────────────────────────────────────────────────────
광고 계정(account) 레벨 성과와 개별 광고(ad) 레벨 합산 성과를 비교해
데이터 정합성을 검증.

[검증 방식]
  1) act_{AD_ACCOUNT_ID}/insights  (level=account) 로 계정 전체 성과 수집
  2) act_{AD_ACCOUNT_ID}/insights  (level=ad)      로 모든 광고의 성과를 페이지네이션
     끝까지 수집 후 직접 합산
  3) 두 값을 비교 → 차이율이 TOLERANCE(%) 초과 시 WARN

[비교 대상 지표]
  ● 직접 합산 (additive): spend, impressions, clicks, inline_post_engagement,
    link_click, landing_page_view, add_to_cart, purchases, view_content,
    initiate_checkout, complete_registration, post_reaction, comment,
    onsite_conversion.post_save, video_30_sec_watched_actions,
    video_p25/p50/p75/p100_watched_actions, video_thruplay_watched_actions
  ● 역산 비교 (derived): ctr, cpc, cpm, purchase_roas
      - Meta API의 계정 레벨 값과
        광고 합산 지표로 직접 계산한 값을 비교
      - ctr  = 합산 clicks / 합산 impressions × 100
      - cpc  = 합산 spend / 합산 clicks
      - cpm  = 합산 spend / 합산 impressions × 1000
      - purchase_roas = 합산 action_values(purchase) / 합산 spend
  ● 비교 불가 (non-additive): reach (중복 제거 유니크 수),
    frequency (impressions/reach — reach가 non-additive라 역산 불가)

[입력 필요]
  CONFIG 딕셔너리에 AD_ACCOUNT_ID 를 채워넣고 실행.
  META_ACCESS_TOKEN 은 같은 디렉터리의 .env 에서 자동 로드됨.

[실행 방법]
  pip install requests python-dotenv
  python meta_account_ad_validator.py
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ====================================================================
# ★ 입력값 ★
# ====================================================================
CONFIG = {
    "access_token":   os.environ["META_ACCESS_TOKEN"],
    "ad_account_id":  "act_799496024940107",   # 예: "act_1234567890"
}

# 검증 기간 (기본: 최근 30일)
DATE_START = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
DATE_END   = datetime.now().strftime("%Y-%m-%d")

# 계정-광고 합산 차이 허용 임계값 (%)
TOLERANCE = 1.0

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
# ====================================================================


# ====================================================================
# 결과 수집 및 출력 유틸
# ====================================================================
_results: list[dict] = []

def _record(label: str, status: str, notes: list[str] = None, raw=None):
    _results.append({"label": label, "status": status, "notes": notes or [], "raw": raw})

def ok(label: str, notes: list[str] = None, raw=None):
    _record(label, "✅ OK", notes, raw)

def warn(label: str, notes: list[str] = None, raw=None):
    _record(label, "⚠️  WARN", notes, raw)

def fail(label: str, notes: list[str] = None, raw=None):
    _record(label, "❌ FAIL", notes, raw)

def info(label: str, notes: list[str] = None, raw=None):
    _record(label, "ℹ️  INFO", notes, raw)

def print_summary():
    print("\n" + "=" * 72)
    print("  검증 결과 요약")
    print("=" * 72)
    n_ok   = sum(1 for r in _results if r["status"] == "✅ OK")
    n_warn = sum(1 for r in _results if r["status"] == "⚠️  WARN")
    n_fail = sum(1 for r in _results if r["status"] == "❌ FAIL")
    n_info = sum(1 for r in _results if r["status"] == "ℹ️  INFO")
    print(f"  총 {len(_results)}개 항목   ✅ {n_ok}   ⚠️  {n_warn}   ❌ {n_fail}   ℹ️  {n_info}")
    print("-" * 72)
    for r in _results:
        print(f"  {r['status']}  {r['label']}")
        for n in r["notes"]:
            print(f"           → {n}")
    print("=" * 72)


# ====================================================================
# Graph API GET 래퍼
# ====================================================================
def graph_get(path: str, params: dict = None) -> dict | None:
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
            print(f"  [API 오류] {path}: {data['error']}")
            return None

    return data


def graph_get_verbose(path: str, params: dict = None) -> tuple[dict | None, str | None]:
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


def get_all_pages(path: str, params: dict = None) -> list[dict]:
    """페이지네이션을 끝까지 소비해 data[] 전체 반환."""
    results: list[dict] = []
    data = graph_get(path, {"limit": 500, **(params or {})})
    if not data:
        return results
    results.extend(data.get("data", []))

    while True:
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        try:
            r = requests.get(next_url, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"  [페이지네이션 오류] {e}")
            break
        if "error" in data:
            print(f"  [페이지네이션 API 오류] {data['error']}")
            break
        results.extend(data.get("data", []))

    return results


# ====================================================================
# 합산 헬퍼
# ====================================================================
def _sum_actions(rows: list[dict], action_type: str) -> float:
    """rows 의 actions[] 에서 특정 action_type 값 합산."""
    total = 0.0
    for row in rows:
        for a in row.get("actions", []):
            if a.get("action_type") == action_type:
                total += float(a.get("value", 0))
    return total


def _sum_action_values(rows: list[dict], action_type: str) -> float:
    """rows 의 action_values[] 에서 특정 action_type 전환 가치 합산."""
    total = 0.0
    for row in rows:
        for a in row.get("action_values", []):
            if a.get("action_type") == action_type:
                total += float(a.get("value", 0))
    return total


def _sum_video_field(rows: list[dict], field_name: str) -> float:
    """rows 의 video 관련 배열 필드([{value:...}]) 합산."""
    total = 0.0
    for row in rows:
        for item in row.get(field_name, []):
            total += float(item.get("value", 0))
    return total


def _sum_direct(rows: list[dict], field_name: str) -> float:
    """rows 의 직접 수치 필드 합산."""
    total = 0.0
    for row in rows:
        v = row.get(field_name)
        if v is not None:
            total += float(v)
    return total


def _pct_diff(account_val: float, ad_sum: float) -> float | None:
    """account_val 대비 차이율(%). account_val == 0 이면 None."""
    if account_val == 0:
        return None
    return abs(account_val - ad_sum) / account_val * 100


def _compare(label: str, account_val: float, ad_sum: float):
    """두 값을 비교해 결과 기록."""
    pct = _pct_diff(account_val, ad_sum)
    notes = [
        f"계정 레벨: {account_val:,.2f}",
        f"광고 합산: {ad_sum:,.2f}",
    ]
    if pct is None:
        if ad_sum == 0:
            ok(label, notes + ["두 값 모두 0 — 해당 없음"])
        else:
            warn(label, notes + [f"계정 레벨이 0인데 광고 합산은 {ad_sum:,.2f}"])
        return

    notes.append(f"차이율: {pct:.4f}%  (임계값: {TOLERANCE}%)")
    if pct <= TOLERANCE:
        ok(label, notes)
    else:
        warn(label, notes + [f"차이율 {pct:.4f}% 가 허용 임계값 {TOLERANCE}% 초과"])


# ====================================================================
# §0. 토큰 유효성
# ====================================================================
def check_token():
    print("\n── §0. 토큰 유효성 ──────────────────────────────────────────────")
    data, err = graph_get_verbose("me", {"fields": "id,name"})
    if data:
        ok("토큰 유효성", [f"id={data.get('id')}  name={data.get('name')}"])
    else:
        fail("토큰 유효성", [err or "알 수 없는 오류"])
        print("  ⛔ 토큰이 유효하지 않아 이후 검증을 중단합니다.")
        raise SystemExit(1)


# ====================================================================
# §1. 계정 레벨 성과 수집
# ====================================================================
_INSIGHT_FIELDS = ",".join([
    "spend", "impressions", "clicks", "inline_post_engagement",
    "actions", "action_values",
    "video_30_sec_watched_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_thruplay_watched_actions",
])

_ACTION_TYPES = [
    "link_click",
    "landing_page_view",
    "offsite_conversion.fb_pixel_add_to_cart",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_view_content",
    "offsite_conversion.fb_pixel_initiate_checkout",
    "offsite_conversion.fb_pixel_complete_registration",
    "post_reaction",
    "comment",
    "onsite_conversion.post_save",
]

_VIDEO_FIELDS = [
    "video_30_sec_watched_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_thruplay_watched_actions",
]

_DIRECT_FIELDS = ["spend", "impressions", "clicks", "inline_post_engagement"]

_NON_ADDITIVE = {
    "reach":      "중복 제거 유니크 수 — 광고 합산 시 동일 유저 중복 계산으로 비교 불가",
    "frequency":  "impressions/reach 파생 비율 — reach가 non-additive이므로 역산 불가",
}

# 역산 가능한 비율 지표: Meta API 계정 레벨 값 + 광고 합산 역산 값 비교
# purchase_roas 의 경우 Meta는 omni_purchase(온·오프라인 합산)로 계산하므로
# 픽셀 기준(fb_pixel_purchase)과 소폭 차이날 수 있음 — 두 action_type 모두 시도
_PURCHASE_ACTION_TYPES = [
    "offsite_conversion.fb_pixel_purchase",  # 픽셀 전환 (웹)
    "omni_purchase",                         # Meta 내부 통합 기준 (purchase_roas 계산 기준)
]


def fetch_account_insights(act_id: str) -> list[dict]:
    print(f"\n  [§1] 계정 레벨 insights 수집 중 ({act_id})...")
    data, err = graph_get_verbose(
        f"{act_id}/insights",
        {
            "fields":        _INSIGHT_FIELDS,
            "level":         "account",
            "time_range":    json.dumps({"since": DATE_START, "until": DATE_END}),
            "time_increment": "all_days",   # 전체 기간 단일 집계
        },
    )
    if not data:
        fail("계정 레벨 insights 수집", [err or "응답 없음"])
        return []

    rows = data.get("data", [])
    if not rows:
        warn("계정 레벨 insights 수집", ["기간 내 성과 데이터 없음"])
        return []

    ok("계정 레벨 insights 수집", [f"{len(rows)}개 행 수신"])
    return rows


# ====================================================================
# §2. 광고 레벨 성과 전체 수집 (페이지네이션)
# ====================================================================
def fetch_ad_level_insights(act_id: str) -> list[dict]:
    print(f"\n  [§2] 광고(ad) 레벨 insights 전체 수집 중 ({act_id})...")
    rows = get_all_pages(
        f"{act_id}/insights",
        {
            "fields":         _INSIGHT_FIELDS,
            "level":          "ad",
            "time_range":     json.dumps({"since": DATE_START, "until": DATE_END}),
            "time_increment": "all_days",
        },
    )
    print(f"  → 총 {len(rows)}개 광고 행 수신")
    if rows:
        ok("광고 레벨 insights 수집", [f"총 {len(rows)}개 광고 행"])
    else:
        warn("광고 레벨 insights 수집", ["기간 내 성과 있는 광고 없음"])
    return rows


# ====================================================================
# §3. 계정 vs 광고 합산 비교
# ====================================================================
def compare(account_rows: list[dict], ad_rows: list[dict]):
    print("\n── §3. 계정 레벨 vs 광고 합산 비교 ─────────────────────────────")

    if not account_rows or not ad_rows:
        warn("비교 불가", ["계정 또는 광고 레벨 데이터 없음 — 비교 건너뜀"])
        return

    # 3-A. 직접 필드 비교
    print("\n  [3-A] 직접 수치 필드")
    for field in _DIRECT_FIELDS:
        acc_val = _sum_direct(account_rows, field)
        ad_val  = _sum_direct(ad_rows, field)
        _compare(f"[직접] {field}", acc_val, ad_val)

    # 3-B. actions 필드 비교
    print("\n  [3-B] actions 필드")
    for at in _ACTION_TYPES:
        acc_val = _sum_actions(account_rows, at)
        ad_val  = _sum_actions(ad_rows, at)
        # 두 값이 모두 0이면 해당 기간에 발생 없음 — 비교 의미 없으므로 INFO 처리
        if acc_val == 0 and ad_val == 0:
            info(
                f"[actions] {at}",
                ["계정·광고 모두 0 — 해당 기간 미발생 또는 해당 캠페인 없음"],
            )
        else:
            _compare(f"[actions] {at}", acc_val, ad_val)

    # 3-C. 비디오 필드 비교
    print("\n  [3-C] 비디오 필드")
    for vf in _VIDEO_FIELDS:
        acc_val = _sum_video_field(account_rows, vf)
        ad_val  = _sum_video_field(ad_rows, vf)
        if acc_val == 0 and ad_val == 0:
            info(f"[video] {vf}", ["계정·광고 모두 0 — 비디오 소재 없거나 해당 없음"])
        else:
            _compare(f"[video] {vf}", acc_val, ad_val)

    # 3-D. 역산 비교: ctr / cpc / cpm / purchase_roas
    print("\n  [3-D] 역산 비율 지표 (광고 합산으로 재계산 후 계정 레벨 API 값과 비교)")

    act_id = CONFIG["ad_account_id"]

    # 계정 레벨 비율 지표를 API에서 직접 수집
    derived_api_data, derived_err = graph_get_verbose(
        f"{act_id}/insights",
        {
            "fields":         "ctr,cpc,cpm,purchase_roas",
            "level":          "account",
            "time_range":     json.dumps({"since": DATE_START, "until": DATE_END}),
            "time_increment": "all_days",
        },
    )
    derived_api_rows = (derived_api_data or {}).get("data", [])
    derived_api = derived_api_rows[0] if derived_api_rows else {}

    if not derived_api and derived_err:
        warn("역산 비율 지표 — 계정 레벨 API 조회 실패", [derived_err])

    # 광고 합산에서 공통 기반 지표 추출
    ad_impressions = _sum_direct(ad_rows, "impressions")
    ad_clicks      = _sum_direct(ad_rows, "clicks")
    ad_spend       = _sum_direct(ad_rows, "spend")

    # CTR: clicks / impressions × 100
    api_ctr = float(derived_api["ctr"]) if "ctr" in derived_api else None
    if ad_impressions > 0:
        computed_ctr = ad_clicks / ad_impressions * 100
        if api_ctr is not None:
            _compare("[역산] ctr (%)", api_ctr, computed_ctr)
        else:
            info("[역산] ctr", [f"계정 API 값 없음  광고 역산: {computed_ctr:.4f}%"])
    else:
        info("[역산] ctr", ["impressions = 0 — 계산 불가"])

    # CPC: spend / clicks
    api_cpc = float(derived_api["cpc"]) if "cpc" in derived_api else None
    if ad_clicks > 0:
        computed_cpc = ad_spend / ad_clicks
        if api_cpc is not None:
            _compare("[역산] cpc (원/click)", api_cpc, computed_cpc)
        else:
            info("[역산] cpc", [f"계정 API 값 없음  광고 역산: {computed_cpc:.2f}"])
    else:
        info("[역산] cpc", ["clicks = 0 — 계산 불가"])

    # CPM: spend / impressions × 1000
    api_cpm = float(derived_api["cpm"]) if "cpm" in derived_api else None
    if ad_impressions > 0:
        computed_cpm = ad_spend / ad_impressions * 1000
        if api_cpm is not None:
            _compare("[역산] cpm (원/1000 imp)", api_cpm, computed_cpm)
        else:
            info("[역산] cpm", [f"계정 API 값 없음  광고 역산: {computed_cpm:.2f}"])
    else:
        info("[역산] cpm", ["impressions = 0 — 계산 불가"])

    # purchase_roas: action_values(purchase) / spend
    # Meta의 purchase_roas는 omni_purchase 기준이므로 두 action_type 모두 시도
    api_roas_list = derived_api.get("purchase_roas", [])
    # purchase_roas 는 [{action_type: "omni_purchase", value: "X.XX"}, ...] 형태
    api_roas_val = None
    api_roas_at  = None
    for item in (api_roas_list if isinstance(api_roas_list, list) else []):
        api_roas_val = float(item.get("value", 0))
        api_roas_at  = item.get("action_type", "")
        break  # 첫 번째(omni_purchase) 사용

    if ad_spend > 0:
        for purchase_at in _PURCHASE_ACTION_TYPES:
            purchase_value = _sum_action_values(ad_rows, purchase_at)
            if purchase_value > 0:
                computed_roas = purchase_value / ad_spend
                label = f"[역산] purchase_roas (action_type={purchase_at})"
                if api_roas_val is not None:
                    notes_extra = []
                    if api_roas_at and api_roas_at != purchase_at:
                        notes_extra.append(
                            f"※ Meta API는 '{api_roas_at}' 기준 — action_type 차이로 소폭 오차 가능"
                        )
                    _compare(label, api_roas_val, computed_roas)
                    for n in notes_extra:
                        # 마지막 결과에 note 추가
                        _results[-1]["notes"].append(n)
                else:
                    info(label, [f"계정 API 값 없음  광고 역산: {computed_roas:.4f}"])
                break  # 첫 번째로 값이 있는 action_type 사용
        else:
            # 두 action_type 모두 0
            if api_roas_val is not None:
                info(
                    "[역산] purchase_roas",
                    [
                        f"계정 API 값: {api_roas_val:.4f}",
                        "광고 레벨 action_values(purchase) 합산 = 0",
                        f"→ 시도 action_type: {_PURCHASE_ACTION_TYPES}",
                        "→ 해당 기간 구매 전환 없거나 픽셀 미설치 확인 필요",
                    ],
                )
            else:
                info("[역산] purchase_roas", ["계정·광고 모두 0 — 해당 없음"])
    else:
        info("[역산] purchase_roas", ["spend = 0 — 계산 불가"])

    # 3-E. 비교 불가 지표 안내 (reach, frequency)
    print("\n  [3-E] 비교 불가 지표 (non-additive) — 참고용 계정 레벨 값만 출력")
    na_data, na_err = graph_get_verbose(
        f"{act_id}/insights",
        {
            "fields":         ",".join(_NON_ADDITIVE.keys()),
            "level":          "account",
            "time_range":     json.dumps({"since": DATE_START, "until": DATE_END}),
            "time_increment": "all_days",
        },
    )
    na_rows = (na_data or {}).get("data", [])
    na_row = na_rows[0] if na_rows else {}

    for field, reason in _NON_ADDITIVE.items():
        val = na_row.get(field, "N/A")
        info(
            f"[non-additive] {field}",
            [f"계정 레벨 값: {val}", f"광고 합산 비교 불가 — {reason}"],
        )


# ====================================================================
# §4. 광고 레벨 커버리지 확인 (계정 spend 대비 수집된 광고 spend 비율)
# ====================================================================
def check_coverage(account_rows: list[dict], ad_rows: list[dict]):
    print("\n── §4. 광고 커버리지 확인 ───────────────────────────────────────")

    acc_spend = _sum_direct(account_rows, "spend")
    ad_spend  = _sum_direct(ad_rows, "spend")
    coverage  = (ad_spend / acc_spend * 100) if acc_spend > 0 else None

    if coverage is None:
        info("spend 커버리지", ["계정 레벨 spend = 0 — 커버리지 계산 불가"])
        return

    notes = [
        f"계정 spend: {acc_spend:,.2f}",
        f"광고 합산 spend: {ad_spend:,.2f}",
        f"커버리지: {coverage:.2f}%",
    ]
    if coverage >= (100 - TOLERANCE):
        ok("spend 커버리지 (광고 합산 / 계정 전체)", notes)
    else:
        warn(
            "spend 커버리지 (광고 합산 / 계정 전체)",
            notes + [
                f"커버리지 {coverage:.2f}% — {100-TOLERANCE:.1f}% 미만",
                "→ 일부 광고가 누락됐을 수 있습니다 (삭제된 광고, 권한 문제 등)",
            ],
        )


# ====================================================================
# main
# ====================================================================
if __name__ == "__main__":
    if CONFIG["ad_account_id"].startswith("YOUR_"):
        print("=" * 60)
        print("  ⛔ CONFIG['ad_account_id'] 를 실제 값으로 채워주세요.")
        print("  예: 'act_1234567890'")
        print("=" * 60)
        raise SystemExit(1)

    act_id = CONFIG["ad_account_id"]
    if not act_id.startswith("act_"):
        act_id = f"act_{act_id}"
        CONFIG["ad_account_id"] = act_id

    print(f"\n{'='*72}")
    print(f"  Meta 광고 계정 vs 광고 합산 정합성 검증")
    print(f"  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"  계정: {act_id}")
    print(f"  조회 기간: {DATE_START} ~ {DATE_END}")
    print(f"  허용 오차: {TOLERANCE}%")
    print(f"  API 버전: {GRAPH_API_VERSION}")
    print(f"{'='*72}")

    check_token()

    account_rows = fetch_account_insights(act_id)
    ad_rows      = fetch_ad_level_insights(act_id)

    compare(account_rows, ad_rows)
    check_coverage(account_rows, ad_rows)

    print_summary()
