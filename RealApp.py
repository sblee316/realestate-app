import streamlit as st
import pandas as pd
import requests
from io import BytesIO
import time
import re

# 네이버 쿠키와 Authorization 토큰 하드코딩
NAVER_COOKIE = "NNB=BNRWYFSV5QCWQ; NAC=aHfIDIBKjunGA; _fwb=53hk3J7S4SJqiwRur46zDt.1745741103362; _fwb=53hk3J7S4SJqiwRur46zDt.1745741103362; nhn.realestate.article.rlet_type_cd=A01; nhn.realestate.article.trade_type_cd=\"\"; nhn.realestate.article.ipaddress_city=4100000000; NACT=1; landHomeFlashUseYn=Y; SRT30=1751262643; SRT5=1751263329; realestate.beta.lastclick.cortar=4100000000; REALESTATE=Mon%20Jun%2030%202025%2015%3A05%3A09%20GMT%2B0900%20(Korean%20Standard%20Time); PROP_TEST_KEY=1751263509586.3171124cee5dac0547c0581f6e378f18ccc4cbd8ac68cdf0a15e08774de17caf; PROP_TEST_ID=3780cec4d8706ce72414a21bf45e987b4ab9b03fc6872d286d2bba344d0a0368; BUC=3WwiU2rSnjvBjQKWa_l5noDr9MuuM71NIIIKTba1Zys="
NAVER_AUTH = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IlJFQUxFU1RBVEUiLCJpYXQiOjE3NTEyNjM1MDksImV4cCI6MTc1MTI3NDMwOX0.QF5wiBIQFeC_U1lJ3wlnioozAbXBgUvaC5rHWlOAzho"

# 법정동코드 데이터 불러오기 (탭 구분)
law_df = pd.read_csv('law_code.txt', sep='\t', dtype=str, encoding='cp949')
law_df = law_df[law_df['폐지여부'] == '존재']  # 폐지된 동 제외

# 시/도, 시/군/구, 동/읍/면 컬럼 분리
def split_law_name(row):
    parts = row['법정동명'].split()
    return pd.Series({
        '시도': parts[0] if len(parts) > 0 else '',
        '시군구': parts[1] if len(parts) > 1 else '',
        '동': parts[2] if len(parts) > 2 else ''
    })
law_df = pd.concat([law_df, law_df.apply(split_law_name, axis=1)], axis=1)

# 부동산 유형 매핑 (예시)
TYPE_CODE = {
    '사무실': 'SMS',
    '상가': 'SG',
    '아파트': 'APT',
    '오피스텔': 'OPST',
}

def parse_korean_price(val):
    if not val or val == '없음':
        return 0
    val = val.replace(',', '').replace(' ', '')
    match = re.match(r'(?:(\d+)억)?(\d+)?', val)
    if not match:
        return 0
    uk = int(match.group(1)) if match.group(1) else 0
    man = int(match.group(2)) if match.group(2) else 0
    return uk * 10000 + man

def collect_real_estate_data(cortarNo, property_type, price_min=0, price_max=900000000, area_min=0, area_max=900000000, page=1, cookie_str=None, auth_token=None, full_address=None):
    realEstateType = TYPE_CODE.get(property_type, 'SMS')
    url = "https://new.land.naver.com/api/articles"
    params = {
        "cortarNo": cortarNo,
        "order": "rank",
        "realEstateType": realEstateType,
        # 가격 범위는 임대료(rentPrc) 기준
        "rentPriceMin": price_min,
        "rentPriceMax": price_max,
        # 면적 범위는 전용면적(area2) 기준
        "area2Min": area_min,
        "area2Max": area_max,
        "page": page,
        "priceType": "RETAIL",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://new.land.naver.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Connection": "keep-alive",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        st.warning(f"API 요청 실패: {response.status_code}")
        return pd.DataFrame()
    data = response.json()
    articles = data.get('articleList', [])
    if not articles:
        st.info("검색 결과가 없습니다.")
        return pd.DataFrame()
    # 주소 처리
    if full_address is None:
        global sido, sigungu, dong
        full_address = f"{sido} {sigungu} {dong}"
    rows = []
    for art in articles:
        floor_info = art.get('floorInfo', '')
        if '/' in floor_info:
            floor_split = floor_info.split('/')
            floor_current = floor_split[0].strip()
            floor_total = floor_split[1].strip()
        else:
            floor_current = floor_info
            floor_total = floor_info
        rows.append({
            '매물명': art.get('articleName'),
            '보증금(만원)': parse_korean_price(art.get('dealOrWarrantPrc')),
            '임대료(만원)': parse_korean_price(art.get('rentPrc')),
            '주소': full_address,
            '계약면적(㎡)': art.get('area1'),
            '전용면적(㎡)': art.get('area2'),
            '해당층': floor_current,
            '전체층': floor_total,
            '매물ID': art.get('articleNo'),
        })
    df = pd.DataFrame(rows)
    return df

def collect_all_real_estate_data(cortarNo, property_type, price_min, price_max, area_min, area_max, cookie_str=None, auth_token=None, max_pages=5, full_address=None):
    all_df = []
    for page in range(1, max_pages+1):
        df = collect_real_estate_data(
            cortarNo, property_type, price_min, price_max, area_min, area_max,
            page=page, cookie_str=cookie_str, auth_token=auth_token, full_address=full_address
        )
        if df.empty:
            break
        all_df.append(df)
        if len(df) < 20:
            break
    if all_df:
        return pd.concat(all_df, ignore_index=True)
    else:
        return pd.DataFrame()

st.title("🏢 부동산 시세 조사기 (전국 행정구역 지원)")

# 시/도 선택
sido_list = law_df[law_df['법정동코드'].str.endswith('00000000')]['시도'].unique()
sido = st.selectbox('시/도 선택', sido_list)

# 시/군/구 선택
sigungu_df = law_df[(law_df['시도'] == sido) & (law_df['법정동코드'].str.endswith('00000')) & (~law_df['법정동코드'].str.endswith('00000000'))]
sigungu_list = sigungu_df['시군구'].unique()
sigungu = st.selectbox('시/군/구 선택', sigungu_list)

# 동/읍/면 선택
dong_df = law_df[
    (law_df['시도'] == sido) &
    (law_df['시군구'] == sigungu) &
    (~law_df['법정동코드'].str.endswith('00000'))
]
dong_list = dong_df['동'].dropna().unique()
dong = st.selectbox('동/읍/면 선택', dong_list)

# 선택된 동의 법정동코드
cortarNo = dong_df[dong_df['동'] == dong]['법정동코드'].values[0]

property_type = st.selectbox("부동산 유형을 선택하세요", list(TYPE_CODE.keys()))

# 임대료(만원 단위) 슬라이더: 0~10000
rent_range = st.slider(
    "임대료 범위(만원)",
    min_value=0, max_value=10000, value=(0, 10000), step=10
)
price_min = rent_range[0] * 10000
price_max = rent_range[1] * 10000

# 전용면적(㎡) 슬라이더: 0~10000
area_range = st.slider(
    "전용면적 범위(㎡)",
    min_value=0, max_value=10000, value=(0, 10000), step=1
)
area_min = area_range[0]
area_max = area_range[1]

uploaded_file = st.file_uploader("법정동명 리스트 엑셀 업로드 (법정동명 컬럼 필수)", type=["xlsx"])

if uploaded_file is not None:
    if st.button("시세 조사 시작"):
        input_df = pd.read_excel(uploaded_file)
        if '법정동명' not in input_df.columns:
            st.error('엑셀에 반드시 "법정동명" 컬럼이 있어야 합니다.')
        else:
            law_names = input_df['법정동명'].dropna().unique()
            result_dict = {}
            for law_name in law_names:
                row = law_df[law_df['법정동명'] == law_name]
                if row.empty:
                    continue
                cortarNo = row['법정동코드'].values[0]
                df = collect_all_real_estate_data(
                    cortarNo, '사무실', 0, 100000000, 0, 10000,
                    cookie_str=NAVER_COOKIE, auth_token=NAVER_AUTH, max_pages=5,
                    full_address=law_name
                )
                result_dict[law_name] = df
            if result_dict:
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    for sheet_name, df in result_dict.items():
                        if not df.empty:
                            safe_sheet_name = sheet_name[:31].replace('/', '-')
                            df.to_excel(writer, index=False, sheet_name=safe_sheet_name)
                st.download_button(
                    label="엑셀 다운로드(법정동별 시트)",
                    data=output.getvalue(),
                    file_name='naver_land_multi_sheet.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
            else:
                st.warning('조회 결과가 없습니다. (법정동명이 잘못되었거나 결과 없음)')
else:
    # 업로드 파일이 없으면 기존 단일 조회 UI 및 버튼 노출
    # (아래 기존 단일 조회 코드 유지)
    if st.button("시세 조사 시작"):
        with st.spinner("조사 중입니다..."):
            df = collect_all_real_estate_data(
                cortarNo, property_type, price_min, price_max, area_min, area_max,
                cookie_str=NAVER_COOKIE, auth_token=NAVER_AUTH,
                max_pages=5
            )
            if not df.empty:
                st.dataframe(df)
                def to_excel(df):
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False)
                    return output.getvalue()
                st.download_button(
                    label="엑셀 다운로드",
                    data=to_excel(df),
                    file_name='naver_land_api_results.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
            else:
                st.warning("검색 결과가 없습니다.") 