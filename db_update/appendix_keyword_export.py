"""
keyword_export.py

보고서 별첨 테이블의 풀버전을 xlsx로 추출.
개수 제한 없이 4개 탭으로 저장:
  1. 많이 사용한 업종 필수 키워드 - 노출
  2. 많이 사용한 업종 필수 키워드 - 클릭
  3. 많이 사용한 브랜드 변수 키워드 - 노출
  4. 많이 사용한 브랜드 변수 키워드 - 클릭

출력 경로: static/appendix/
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# db_update/ 에서 실행 시 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import re

import numpy as np
import pandas as pd
from scripts.db_connector import get_engine
from scripts.processor import _normalize_keyword_by_pos, _best_adverb_score, kiwi, VERB_ADJ_TAGS

_KOREAN_RE = re.compile(r"[가-힣]")

# ── 설정 (main.py의 config와 동일하게 맞추세요) ──────────────────────────────
CONFIG = {
    "target_id": 29,
    "start": "2025-11-17",
    "end": "2026-03-23",
}
# ─────────────────────────────────────────────────────────────────────────────


def get_essence_target_performance(account_id, date_start, date_end):
    """업종 필수 키워드 성과 (개수 제한 없음)"""
    engine = get_engine()
    query = f"""
    SELECT
        res.single_ess AS "키워드",
        res.total_ad_count AS "등장 광고 수",
        MAX(CASE WHEN res.imp_rank = 1 THEN res.age || ' ' || res.gender END) AS "최다 노출 타겟",
        MAX(CASE WHEN res.imp_rank = 1 THEN res.target_imp END)::bigint AS "타겟 노출량",
        ROUND(MAX(CASE WHEN res.imp_rank = 1 THEN res.target_imp END)::numeric / NULLIF(MAX(res.total_imp), 0) * 100, 1) || '%%' AS "노출 비중",
        MAX(res.total_imp)::bigint AS "총 노출량",
        MAX(CASE WHEN res.clk_rank = 1 THEN res.age || ' ' || res.gender END) AS "최다 클릭 타겟",
        MAX(CASE WHEN res.clk_rank = 1 THEN res.target_clk END)::bigint AS "타겟 클릭량",
        ROUND(MAX(CASE WHEN res.clk_rank = 1 THEN res.target_clk END)::numeric / NULLIF(MAX(res.total_clk), 0) * 100, 1) || '%%' AS "클릭 비중",
        MAX(res.total_clk)::bigint AS "총 클릭량"
    FROM (
        SELECT
            ts.single_ess, ts.age, ts.gender, ts.target_imp, ts.target_clk,
            summ.total_ad_count,
            SUM(ts.target_imp) OVER(PARTITION BY ts.single_ess) AS total_imp,
            SUM(ts.target_clk) OVER(PARTITION BY ts.single_ess) AS total_clk,
            RANK() OVER (PARTITION BY ts.single_ess ORDER BY ts.target_imp DESC, ts.age) AS imp_rank,
            RANK() OVER (PARTITION BY ts.single_ess ORDER BY ts.target_clk DESC, ts.age) AS clk_rank
        FROM (
            SELECT
                ak_u.single_ess, p.age, p.gender,
                SUM(p.imp) AS target_imp,
                SUM(p.clk) AS target_clk
            FROM (
                SELECT ad_id, UNNEST(essential_keywords) AS single_ess
                FROM ad_keyword
                WHERE essential_keywords IS NOT NULL AND ARRAY_LENGTH(essential_keywords, 1) > 0
            ) ak_u
            INNER JOIN (
                SELECT
                    apd.ad_id, apd.age, apd.gender,
                    SUM(apd.impressions) AS imp, SUM(apd.clicks) AS clk
                FROM ad_performance_daily apd
                INNER JOIN ad a ON apd.ad_id = a.ad_id
                INNER JOIN ad_set ads ON a.ad_set_id = ads.ad_set_id
                INNER JOIN campaign c ON ads.campaign_id = c.campaign_id
                WHERE a.account_id = {account_id}
                AND apd.date >= '{date_start}'::date
                AND apd.date <= DATE_TRUNC('week', '{date_end}'::date)::date
                AND ({account_id} = 3 OR c.campaign_name ~* 'depart|디파트|de;part')
                GROUP BY 1, 2, 3
            ) p ON ak_u.ad_id = p.ad_id
            GROUP BY 1, 2, 3
        ) ts
        INNER JOIN (
            SELECT
                UNNEST(ak.essential_keywords) AS single_ess,
                COUNT(DISTINCT ak.ad_id) AS total_ad_count
            FROM ad_keyword ak
            INNER JOIN ad a ON ak.ad_id = a.ad_id
            INNER JOIN ad_set ads ON a.ad_set_id = ads.ad_set_id
            INNER JOIN campaign c ON ads.campaign_id = c.campaign_id
            INNER JOIN ad_performance_daily apd ON a.ad_id = apd.ad_id
            WHERE a.account_id = {account_id}
            AND apd.date >= '{date_start}'::date
            AND apd.date <= DATE_TRUNC('week', '{date_end}'::date)::date
            AND ({account_id} = 3 OR c.campaign_name ~* 'depart|디파트|de;part')
            GROUP BY 1
        ) summ ON ts.single_ess = summ.single_ess
    ) res
    GROUP BY res.single_ess, res.total_ad_count
    ORDER BY "등장 광고 수" DESC, "총 노출량" DESC;
    """
    return pd.read_sql(query, engine)


def get_brand_name(account_id) -> str:
    """ad_account 테이블에서 brand_name[1]을 조회."""
    engine = get_engine()
    query = f"""
        SELECT brand_name[1] AS brand_name
        FROM ad_account
        WHERE account_id = {account_id}
        LIMIT 1
    """
    df = pd.read_sql(query, engine)
    if not df.empty:
        return str(df.iloc[0]["brand_name"])
    return str(account_id)


def get_variable_target_performance_full(account_id, date_start, date_end):
    """브랜드 변수 키워드 성과 (LIMIT 없음 - 전체)"""
    engine = get_engine()
    query = f"""
    SELECT
        res.single_var AS "키워드",
        res.total_ad_count AS "등장 광고 수",
        MAX(CASE WHEN res.imp_rank = 1 THEN res.age || ' ' || res.gender END) AS "최다 노출 타겟",
        MAX(CASE WHEN res.imp_rank = 1 THEN res.target_imp END)::bigint AS "타겟 노출량",
        ROUND(MAX(CASE WHEN res.imp_rank = 1 THEN res.target_imp END)::numeric / NULLIF(MAX(res.total_imp), 0) * 100, 1) || '%%' AS "노출 비중",
        MAX(res.total_imp)::bigint AS "총 노출량",
        MAX(CASE WHEN res.clk_rank = 1 THEN res.age || ' ' || res.gender END) AS "최다 클릭 타겟",
        MAX(CASE WHEN res.clk_rank = 1 THEN res.target_clk END)::bigint AS "타겟 클릭량",
        ROUND(MAX(CASE WHEN res.clk_rank = 1 THEN res.target_clk END)::numeric / NULLIF(MAX(res.total_clk), 0) * 100, 1) || '%%' AS "클릭 비중",
        MAX(res.total_clk)::bigint AS "총 클릭량"
    FROM (
        SELECT
            ts.single_var, ts.age, ts.gender, ts.target_imp, ts.target_clk,
            summ.total_ad_count,
            SUM(ts.target_imp) OVER(PARTITION BY ts.single_var) AS total_imp,
            SUM(ts.target_clk) OVER(PARTITION BY ts.single_var) AS total_clk,
            RANK() OVER (PARTITION BY ts.single_var ORDER BY ts.target_imp DESC, ts.age) AS imp_rank,
            RANK() OVER (PARTITION BY ts.single_var ORDER BY ts.target_clk DESC, ts.age) AS clk_rank
        FROM (
            SELECT
                ak_u.single_var, p.age, p.gender,
                SUM(p.imp) AS target_imp,
                SUM(p.clk) AS target_clk
            FROM (
                SELECT ad_id, UNNEST(variable_keywords) AS single_var
                FROM ad_keyword
                WHERE variable_keywords IS NOT NULL AND ARRAY_LENGTH(variable_keywords, 1) > 0
            ) ak_u
            INNER JOIN (
                SELECT
                    apd.ad_id, apd.age, apd.gender,
                    SUM(apd.impressions) AS imp, SUM(apd.clicks) AS clk
                FROM ad_performance_daily apd
                INNER JOIN ad a ON apd.ad_id = a.ad_id
                INNER JOIN ad_set ads ON a.ad_set_id = ads.ad_set_id
                INNER JOIN campaign c ON ads.campaign_id = c.campaign_id
                WHERE a.account_id = {account_id}
                AND apd.date >= '{date_start}'::date
                AND apd.date <= DATE_TRUNC('week', '{date_end}'::date)::date
                AND ({account_id} = 3 OR c.campaign_name ~* 'depart|디파트|de;part')
                GROUP BY 1, 2, 3
            ) p ON ak_u.ad_id = p.ad_id
            GROUP BY 1, 2, 3
        ) ts
        INNER JOIN (
            SELECT
                UNNEST(ak.variable_keywords) AS single_var,
                COUNT(DISTINCT ak.ad_id) AS total_ad_count
            FROM ad_keyword ak
            INNER JOIN ad a ON ak.ad_id = a.ad_id
            INNER JOIN ad_set ads ON a.ad_set_id = ads.ad_set_id
            INNER JOIN campaign c ON ads.campaign_id = c.campaign_id
            INNER JOIN ad_performance_daily apd ON a.ad_id = apd.ad_id
            WHERE a.account_id = {account_id}
            AND apd.date >= '{date_start}'::date
            AND apd.date <= DATE_TRUNC('week', '{date_end}'::date)::date
            AND ({account_id} = 3 OR c.campaign_name ~* 'depart|디파트|de;part')
            GROUP BY 1
        ) summ ON ts.single_var = summ.single_var
    ) res
    GROUP BY res.single_var, res.total_ad_count
    ORDER BY "등장 광고 수" DESC, "총 노출량" DESC;
    """
    return pd.read_sql(query, engine)


# ── 표시 형식 변환 (main.py와 동일한 로직) ──────────────────────────────────

def _is_predicate_for_display(token: str) -> bool:
    """main.py _is_predicate_for_display 동일 로직: 형용사/동사 여부 판단."""
    if _normalize_keyword_by_pos(token, "verb_adj") is not None:
        return True

    adverb_score = _best_adverb_score(token)
    best_pred_score = None
    for tokens, score in kiwi.analyze(f"{token}다", top_n=3):
        if not tokens:
            continue
        cand_score = float(score)
        first = next((tok for tok in tokens if tok.tag in VERB_ADJ_TAGS), None)
        if first and first.form == token:
            if best_pred_score is None or cand_score > best_pred_score:
                best_pred_score = cand_score
        if len(tokens) >= 2 and tokens[0].form + tokens[1].form == token:
            if tokens[1].tag in {"XSA", "XSV"}:
                if best_pred_score is None or cand_score > best_pred_score:
                    best_pred_score = cand_score
    if best_pred_score is None:
        return False
    if adverb_score is not None and adverb_score >= best_pred_score:
        return False
    return True


def _append_da_if_predicate(value):
    """main.py _append_da_if_predicate 동일 로직: 형용사/동사에 -다 접미사 부여."""
    if not isinstance(value, str):
        return value
    token = value.strip()
    if not token or token.endswith("다"):
        return value
    if len(token) < 2:
        return value
    if " " in token or not _KOREAN_RE.search(token):
        return value
    if not _is_predicate_for_display(token):
        return value
    return f"{token}다"


def _replace_gender(value):
    """타겟 컬럼의 female/male 표기를 여성/남성으로 변환."""
    if not isinstance(value, str):
        return value
    return value.replace("female", "여성").replace("male", "남성")


def apply_display_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """
    DB에서 가져온 원본 DataFrame에 main.py와 동일한 표시 변환 적용:
      - 키워드 컬럼: 형용사/동사에 -다 접미사
      - 최다 노출/클릭 타겟 컬럼: female→여성, male→남성
    """
    df = df.copy()
    # 키워드 컬럼 (col 0): 형용사/동사 -다 접미사
    keyword_col = df.columns[0]
    df[keyword_col] = df[keyword_col].apply(_append_da_if_predicate)
    # 최다 노출 타겟 컬럼 (col 2): 성별 한글화
    imp_target_col = df.columns[2]
    df[imp_target_col] = df[imp_target_col].apply(_replace_gender)
    # 최다 클릭 타겟 컬럼 (col 6): 성별 한글화
    clk_target_col = df.columns[6]
    df[clk_target_col] = df[clk_target_col].apply(_replace_gender)
    return df


# ─────────────────────────────────────────────────────────────────────────────

def compute_competition_ranks(df) -> list[int]:
    """
    등장 광고 수(col 1) DESC → 총 노출량(col 5) DESC 기준으로
    RANK() 방식 순위를 계산. (동률 시 동일 순위, 다음 순위는 동률 개수만큼 건너뜀)

    SQL ORDER BY 결과가 이미 이 순서로 정렬되어 있으므로
    인접한 행들만 비교하면 됨.
    """
    if df is None or df.empty:
        return []

    ad_count = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0)
    total_imp = pd.to_numeric(df.iloc[:, 5], errors="coerce").fillna(0)
    keys = list(zip(ad_count, total_imp))

    ranks: list[int] = []
    i = 0
    while i < len(keys):
        # 현재 값과 동일한 행이 연속으로 몇 개인지 확인
        j = i
        while j < len(keys) and keys[j] == keys[i]:
            j += 1
        # i ~ j-1 행 모두 동일 순위 (현재 ranks 길이 + 1)
        current_rank = i + 1
        ranks.extend([current_rank] * (j - i))
        i = j

    return ranks


def build_ranked_sheet(df, col_indices, ranks: list[int]):
    """
    df에서 col_indices 컬럼만 추출하고, 앞에 순위 컬럼을 붙여 DataFrame 반환.
    ranks는 compute_competition_ranks()로 미리 계산된 값을 사용.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    temp = df.replace({pd.NA: None, pd.NaT: None, float("nan"): None})
    subset = temp.iloc[:, col_indices].copy()
    subset.insert(0, "랭킹", ranks)
    return subset


def export(target_id, start, end):
    # date_end를 실제 집계 기준(주의 직전 일요일)으로 맞춤 (main.py/to_json.py 동일 로직)
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    actual_end = (end_dt - timedelta(days=end_dt.weekday())).strftime("%Y-%m-%d")

    print(f"업종 필수 키워드 조회 중... (account_id={target_id}, {start} ~ {actual_end})")
    df_ess = get_essence_target_performance(target_id, start, end)
    print(f"  → {len(df_ess)}건")

    print(f"브랜드 변수 키워드 조회 중... (account_id={target_id}, {start} ~ {actual_end})")
    df_var = get_variable_target_performance_full(target_id, start, end)
    print(f"  → {len(df_var)}건")

    print("표시 형식 변환 적용 중... (성별 한글화 / 형용사·동사 -다 접미사)")
    df_ess = apply_display_transforms(df_ess)
    df_var = apply_display_transforms(df_var)

    # 동률 처리 순위 사전 계산 (등장 광고 수 DESC → 총 노출량 DESC 기준, RANK() 방식)
    ess_ranks = compute_competition_ranks(df_ess)
    var_ranks = compute_competition_ranks(df_var)

    tabs = [
        {
            "sheet": "업종 필수 키워드 - 노출",
            "df": df_ess,
            "col_indices": [0, 1, 2, 3, 4, 5],
            "headers": ["랭킹", "키워드", "등장 광고 수", "최다 노출 타겟", "타겟 노출량", "노출 비중", "총 노출량"],
            "ranks": ess_ranks,
        },
        {
            "sheet": "업종 필수 키워드 - 클릭",
            "df": df_ess,
            "col_indices": [0, 1, 6, 7, 8, 9],
            "headers": ["랭킹", "키워드", "등장 광고 수", "최다 클릭 타겟", "타겟 클릭량", "클릭 비중", "총 클릭량"],
            "ranks": ess_ranks,
        },
        {
            "sheet": "브랜드 변수 키워드 - 노출",
            "df": df_var,
            "col_indices": [0, 1, 2, 3, 4, 5],
            "headers": ["랭킹", "키워드", "등장 광고 수", "최다 노출 타겟", "타겟 노출량", "노출 비중", "총 노출량"],
            "ranks": var_ranks,
        },
        {
            "sheet": "브랜드 변수 키워드 - 클릭",
            "df": df_var,
            "col_indices": [0, 1, 6, 7, 8, 9],
            "headers": ["랭킹", "키워드", "등장 광고 수", "최다 클릭 타겟", "타겟 클릭량", "클릭 비중", "총 클릭량"],
            "ranks": var_ranks,
        },
    ]

    brand_name = get_brand_name(target_id)
    print(f"브랜드명: {brand_name}")

    out_dir = Path(__file__).parent.parent / "static" / "appendix"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 파일명의 "/" 는 파일시스템 안전을 위해 전각 슬래시(／)로 대체
    filename = f"[디파트]26년1／4분기별첨_{brand_name}.xlsx"
    out_path = out_dir / filename

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for tab in tabs:
            sheet_df = build_ranked_sheet(tab["df"], tab["col_indices"], tab["ranks"])
            if sheet_df.empty:
                sheet_df = pd.DataFrame(columns=tab["headers"])
            else:
                sheet_df.columns = tab["headers"]
            sheet_df.to_excel(writer, sheet_name=tab["sheet"], index=False)

    print(f"\n✅ 저장 완료: {out_path}")
    return str(out_path)


if __name__ == "__main__":
    export(
        target_id=CONFIG["target_id"],
        start=CONFIG["start"],
        end=CONFIG["end"],
    )
