# 정리(prune) D — docs/reports 중복 사본 및 Kostolany 중간 산출물 삭제 기록

기준 커밋 `52c4940`. 사용자 결정('추천대로')에 따라 (1) docs/reports 의 analysis 원본과 바이트 동일한 HTML 사본, (2) `analysis/kostolany_market_report_2026-08-12/` 의 스크린샷 PNG 와 `equity_curves.pkl` 만 삭제했다. 코드·deploy·analysis 원본·PROGRESS.md 는 수정하지 않았다.

**요약: 삭제 103개(HTML 사본 40개 1.44MB + Kostolany PNG 62개·pkl 1개 83.5MB), 합계 약 85.0MB.**

판정 방법: `docs/reports/X` 의 sha256 을 `analysis/**/*.html` 전체 해시와 대조(파일명이 아니라 내용 기준; 원본 파일명은 대부분 `final_report.html`). 삭제는 항상 docs/reports 쪽 사본만이며 원본은 analysis 에 남아 있다.

## 1. docs/reports 중복 HTML 사본 삭제

참조 확인: 저장소 전체 grep. 코드·app·워크플로·테스트가 가리키는 것은 없었고, 문서 참조는 `docs/reports/README.md`(링크·경로를 원본 `analysis/...` 로 갱신함), 종합 리포트 HTML/`build_report.py` 안의 파일명 **텍스트**(링크 아님, 원본과 바이트 동일해 수정 불가), PROGRESS.md 의 과거 기록(수정 금지)뿐이다. 복구: `git show 52c4940:<경로>`.

| 경로 | 크기(B) | sha256 일치 원본 | sha256 | 참조 확인 |
|---|---|---|---|---|
| `docs/reports/base_rate_monte_carlo_sensitivity_research.html` | 40,494 | `analysis/2026-08-23_base_rate_monte_carlo_sensitivity/final_report.html` | `fcee877abaee320c…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/basket_correlation_structure_predictor_research.html` | 32,460 | `analysis/2026-09-19_basket_correlation_structure_predictor/final_report.html` | `629b869cade767db…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/block_bootstrap_sample_error_quantification_research.html` | 27,032 | `analysis/2026-08-23_block_bootstrap_sample_error_quantification/final_report.html` | `f4864c2fd217a1e5…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/bootstrap_confidence_audit_remaining_verdicts_research.html` | 37,348 | `analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/final_report.html` | `3fe886d158844ae0…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/champion_beta_and_satellite_research.html` | 36,131 | `analysis/2026-08-19_champion_beta_and_satellite_research/final_report.html` | `edac5b641d3349bc…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/champion_parameter_fine_resolution_and_satellite_joint_research.html` | 41,470 | `analysis/2026-08-23_champion_parameter_fine_resolution_and_satellite_joint/final_report.html` | `d5d6875d767b14cc…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/collar_hedge_parameter_sensitivity_research.html` | 37,042 | `analysis/2026-09-14_collar_hedge_parameter_sensitivity/final_report.html` | `f182b77a2fa48302…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/core_filter_bootstrap_and_satellite_weight_extension_research.html` | 31,573 | `analysis/2026-08-30_core_filter_bootstrap_and_satellite_weight_extension/final_report.html` | `7c1650910efc83ee…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/cost_tax_audit_research.html` | 27,967 | `analysis/2026-09-14_cost_tax_audit/final_report.html` | `3407c25a9d1f8d15…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/crisis_sample_expansion_and_risk_frontier_research.html` | 30,739 | `analysis/2026-08-23_crisis_sample_expansion_and_risk_frontier/final_report.html` | `ee6460b574a31262…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/expected_value_reframing_and_continuous_exposure_research.html` | 35,917 | `analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/final_report.html` | `d3743de3b26fa7ee…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/fine_grid_joint_candidate_bootstrap_audit_research.html` | 40,625 | `analysis/2026-09-17_fine_grid_joint_candidate_bootstrap_audit/final_report.html` | `ce250907dbadf2d8…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/historical_era_trend_following_extension_research.html` | 35,354 | `analysis/2026-09-17_historical_era_trend_following_extension/final_report.html` | `938d20fac0efab8e…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/iren_basket_collar_hedge_transplant_research.html` | 33,053 | `analysis/2026-09-14_iren_basket_collar_hedge_transplant/final_report.html` | `8eb0a8e57695a7d1…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/iren_beta_alpha_hedging_research.html` | 51,984 | `analysis/2026-08-19_iren_beta_alpha_hedging/final_report.html` | `ee46626e31abafad…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/iren_volatile_momentum_stocks_research.html` | 62,161 | `analysis/2026-08-16_iren_volatile_momentum_stocks/final_report.html` | `2c0cae1138878b8b…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/joint_parameter_interaction_grid_search_research.html` | 33,004 | `analysis/2026-08-23_joint_parameter_interaction_grid_search/final_report.html` | `0dde586384d3b1d0…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/literature_benchmark_momentum_ranking_research.html` | 34,011 | `analysis/2026-09-14_literature_benchmark/final_report.html` | `53f5bee743f26599…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/live_stock_discovery_snapshot_research.html` | 46,729 | `analysis/2026-09-17_live_tenbagger_screening_snapshot/final_report.html` | `8c47fbc3dbafaebe…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/methodology_meta_audit_2026-09-14.html` | 38,198 | `analysis/2026-09-14_methodology_meta_audit/final_report.html` | `b2d7e3ddca48b296…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/nonai_control_basket_volatility_momentum_research.html` | 31,831 | `analysis/2026-09-14_nonai_control_basket_volatility_momentum/final_report.html` | `16d711ac0124e5ca…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/options_collar_btc_instrument_transplant_research.html` | 31,890 | `analysis/2026-09-15_options_collar_hedge_volatility_momentum_basket/final_report.html` | `1749810d8b264940…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/options_collar_moneyness_tenor_grid_and_placebo_research.html` | 47,154 | `analysis/2026-09-15_options_collar_parameter_sensitivity/final_report.html` | `79d89d84a0b3b708…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/options_hedge_bootstrap_and_combined_system_research.html` | 28,103 | `analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/final_report.html` | `902a3395a8bc1108…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/permutation_and_quality_momentum_research.html` | 59,354 | `analysis/2026-08-19_permutation_and_quality_momentum_research/final_report.html` | `d3a9b6faf83ef141…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/quality_filter_and_satellite_placebo_research.html` | 33,125 | `analysis/2026-08-20_quality_filter_and_satellite_placebo_research/final_report.html` | `92351d71f769ca71…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/regime_conditional_satellite_switch_research.html` | 32,506 | `analysis/2026-08-22_regime_conditional_satellite_switch/final_report.html` | `b0bbd23d98d28453…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/risk_adjusted_momentum_ranking_research.html` | 29,102 | `analysis/2026-08-30_risk_adjusted_momentum_ranking/final_report.html` | `626204d676672ddf…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_correlation_crisis_signal_research.html` | 48,801 | `analysis/2026-09-14_satellite_correlation_crisis_signal/final_report.html` | `a6e22b6655190bc0…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_frontier_and_quality_blend_research.html` | 42,744 | `analysis/2026-08-20_satellite_frontier_and_quality_blend_research/final_report.html` | `ce9bdb8b1ebca70f…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_realtime_stop_and_reentry_research.html` | 31,950 | `analysis/2026-08-22_satellite_realtime_stop_and_reentry_research/final_report.html` | `e7f7fccb97bfafbd…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_signal_upgrade_and_crisis_test_research.html` | 36,777 | `analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/final_report.html` | `3b52b004a14f25aa…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_specific_crisis_signal_research.html` | 30,851 | `analysis/2026-08-22_satellite_specific_crisis_signal_and_2021_case_study/final_report.html` | `664e28d9a087cae7…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/satellite_weight_and_core_filter_expected_value_research.html` | 21,597 | `analysis/2026-08-23_satellite_weight_and_core_filter_expected_value/final_report.html` | `57ed64adcec6cd69…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/strategy_candidate_1_trade_frequency_research.html` | 19,498 | `analysis/2026-09-14_strategy_candidate_1/final_report.html` | `b73fd25b1b782941…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/synthetic_options_tail_hedge_research.html` | 36,296 | `analysis/2026-08-30_synthetic_options_tail_hedge/final_report.html` | `a670a34e82c6050e…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/system_vs_buyhold_and_lookback_robustness_research.html` | 31,407 | `analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/final_report.html` | `f273773fdb72b996…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/track_c_bootstrap_confidence_audit_research.html` | 29,254 | `analysis/2026-08-30_track_c_bootstrap_confidence_audit/final_report.html` | `6561e33aac1343b7…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/vix_fast_crash_signal_and_hybrid_switch_research.html` | 34,159 | `analysis/2026-08-23_vix_fast_crash_signal_and_hybrid_switch/final_report.html` | `c67bde5827a60756…` | README 갱신, 화면/코드 참조 0 |
| `docs/reports/vol_targeting_and_rebalance_frequency_expected_value_research.html` | 31,939 | `analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/final_report.html` | `113ca6e1002a12e4…` | README 갱신, 화면/코드 참조 0 |

## 2. Kostolany 폴더 스크린샷·pkl 삭제

확인: (a) 보고서 `final_report.html` 및 docs/reports 사본은 `<img>`/`.png`/`data:image` 참조가 0건(차트는 chart.js 로 그림) — 보고서 본문은 그대로 유지. (b) `core/ scripts/ app/ deploy/ tests/ scheduler/` 에서 `equity_curves.pkl` 및 `shot_*.png` 읽는 코드 0건. `equity_curves.pkl` 은 폴더 안 분석 스크립트만 다룬다(`run_kostolany_market_analysis.py` 가 생성, `aggregate_and_export.py` 가 읽음) — 재생성 가능한 캐시이며 RESUME_NOTES.md 도 'git에 커밋하지 않는 게 좋음'이라 적었다. `shot_*.png` 는 `check_render.py` 가 만드는 렌더 확인용 캡처. 복구: `git show 52c4940:<경로> > 파일`.

| 경로 | 크기(B) | sha256 | 참조 확인 |
|---|---|---|---|
| `analysis/kostolany_market_report_2026-08-12/equity_curves.pkl` | 19,153,319 | `121cd5359f92187b…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_bear_0.png` | 206,228 | `b1d17bce440f23a8…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_bear_1.png` | 196,668 | `fa0f9c040f40f16e…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_bear_dark.png` | 68,358 | `2e453bdb98239777…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_caveats2.png` | 136,351 | `a53ef17dd2fdbbd0…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_combined_1.png` | 214,308 | `714c8bd9b6e9a82b…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_combined_2.png` | 157,236 | `527a16897d22eb5a…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_combined_3.png` | 155,798 | `3f76846fec45d89a…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_combined_dark1.png` | 215,201 | `dba1dc95c08fea1c…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_combined_full.png` | 192,693 | `03e926a22abb744f…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_concl_final.png` | 119,278 | `a8a1a1383948a7e2…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_conclusion2.png` | 265,911 | `9645aa7a1d3f41d3…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_conclusion3.png` | 315,271 | `19ef7b707bc2f8b8…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_conclusion4.png` | 378,816 | `ecc5ab8b9705925e…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_finalfind_0.png` | 203,663 | `ba431f2d4f86a1b3…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_finalfind_1.png` | 181,836 | `287fc7bb19a34964…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_finalfind_dark.png` | 62,634 | `2bcab3f80e6742db…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full10.png` | 4,572,792 | `94b624226bfc8841…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full11.png` | 5,130,708 | `9002218600b86fed…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full12.png` | 5,205,123 | `d4a72a4a9b7a15f0…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full2.png` | 2,277,536 | `84cfdc92b12a46ae…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full3.png` | 2,561,088 | `00cc26729ed08afe…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full4.png` | 2,906,110 | `2d5a93b778dbfd63…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full5.png` | 3,130,077 | `8d7ed4340e89fb9c…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full6.png` | 3,272,307 | `c4c83728948a7835…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full7.png` | 3,556,401 | `b7310ca6adf25729…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full8.png` | 3,916,687 | `daf784f779a312af…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full9.png` | 4,208,588 | `4eb335ce91d056fc…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full_dark.png` | 2,292,713 | `3d593c6c0394e3cd…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full_dark_final.png` | 5,225,041 | `532ea346e176eb08…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full_page.png` | 2,277,536 | `84cfdc92b12a46ae…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_full_wide.png` | 5,298,410 | `6ae0e6f597ea798f…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_0.png` | 199,866 | `ffda0c932b0ae6cc…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_1.png` | 207,308 | `8ce510b9f31bd4c1…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_2.png` | 188,073 | `9cb6d4b5939f5fa0…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_3.png` | 182,504 | `6730988eb0ee5403…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_dark.png` | 207,342 | `4de419835b91cf4c…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_ledger_fixed.png` | 207,927 | `43c1fcdcdbbf599d…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_chart_fixed.png` | 85,159 | `30ad748aec9a7e46…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_dark.png` | 64,272 | `e45bae952f1e5398…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_fix_0.png` | 242,858 | `c7e3d0bce13cfb71…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_fix_1.png` | 159,451 | `c10c8900af595c1a…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_fix_2.png` | 179,906 | `8ba3718df2caec8d…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_mom_fix_3.png` | 245,285 | `270228a474ac6484…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_momentum_1.png` | 203,212 | `5d1d3b24c3bcf636…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_momentum_2.png` | 179,262 | `86977eb29a1f289a…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_practical_0.png` | 215,557 | `48f0c3d607c0e811…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_practical_1.png` | 232,731 | `c86f6c99763a04c5…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_practical_caveat.png` | 127,545 | `d04086a19726108f…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_practical_dark.png` | 111,416 | `8f062a9ed26f754f…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_practical_fixed.png` | 216,307 | `d0a72040b0869fdd…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_refined.png` | 198,153 | `f2513d365236d11f…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_regime_0.png` | 226,941 | `b305679e2516cbbe…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_regime_1.png` | 208,672 | `1ba45e1fccbbb228…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_toc2.png` | 15,730 | `d4931d0d4952d9f7…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_toc3.png` | 18,149 | `05e4af45182ab28a…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_unbiased_1.png` | 188,869 | `11e4d3143f8d0214…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_unbiased_2.png` | 190,187 | `86d5513757ce7463…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_unbiased_dark.png` | 79,835 | `6f1ffc8b16570538…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_verify1.png` | 172,952 | `2df621468289fe17…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_verify2.png` | 321,143 | `ac87ed1627eed201…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_voltarget_dark.png` | 108,085 | `5bc5831622f7698c…` | 참조 0 |
| `analysis/kostolany_market_report_2026-08-12/shot_voltarget_section.png` | 293,324 | `bf068e0b14f04a9f…` | 참조 0 |

## 보류 / 유지

- `docs/reports/research_program_synthesis.html`(38,564B): analysis 원본과 바이트 동일하지만 `app/pages/11_챔피언_전략.py` 안내 문구가 이 경로를 가리키는 살아 있는 참조라 유지. (app 은 수정하지 않음.)
- `docs/reports/README.md`: 연구 에이전트와 `deploy/progress_reconcile.sh` 사용 파일이라 유지, 링크만 갱신.
- analysis 에 동일 해시 원본이 없는 docs/reports HTML 12개는 유일한 로컬 사본이므로 유지: bull_market_momentum_rotation, engine_architecture_notes, kostolany_market_report_2026-08-12(525KB), market_regime_sector_strength_note, momentum_rotation_2022_dotcom_stress, momentum_rotation_gfc_validation, momentum_rotation_individual_stocks, momentum_rotation_multiasset_extension, momentum_rotation_point_in_time_verdict, quant_lecture_notes, study_notes_fin_engineering, tenbagger_stock_picking_research(해시 불일치).
- Kostolany 폴더의 다른 `.pkl` 8개(`equity_curves_final.pkl` 3.6MB, `momentum_rotation_extended.pkl` 2.3MB 등 약 9MB)는 이번 요청 범위(`equity_curves.pkl`)가 아니라 삭제하지 않았다. `analysis/macro_event_study_2026-08-21` 등 그 외는 손대지 않음.
- 삭제 후 남은 파일명 텍스트 언급(링크 아님): `analysis/2026-09-05_research_program_synthesis/{build_report.py,final_report.html}`, `docs/reports/research_program_synthesis.html`(바이트 동일 사본), `analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/h_bootstrap_audit.py`, `analysis/LATEST_STRATEGY_CANDIDATE.md` 의 코드 표기 이름들. 클릭 링크가 아니라 수정하지 않았다.

## 총 삭제 용량

약 85.0MB (docs/reports 2.6MB→1.2MB, Kostolany 폴더 92MB→12MB).

## 검증

삭제 전 `python -m pytest tests -q` 1739 passed. 삭제 후 1739 passed (동일). README 상대 링크 깨짐 0건.
