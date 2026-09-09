# Meta Agent Required-Agent Selection

## Model Comparison

| Model | Precision | Recall | F1 | Exact | Total tokens |
|---|---:|---:|---:|---:|---:|
| `gemini-3.8-flash` | 0.576 | 1.000 | 0.731 | 2 / 12 | 12,511 |
| `gemini-3.7-flash` | 0.576 | 1.000 | 0.731 | 1 / 12 | 11,330 |

## Per-GT Agent Sets

| GT | Required agents | Gemini 3.8 Flash | Gemini 3.7 Flash |
|---|---|---|---|
| `glucose_case_01` | pancreas, liver, skeletal_muscle | pancreas, liver, skeletal_muscle, kidney, adipose_tissue | pancreas, liver, skeletal_muscle, kidney, adipose_tissue |
| `glucose_case_02` | pancreas, liver | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, adipose_tissue | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, adipose_tissue |
| `glucose_case_03_diabetes_renal` | pancreas, skeletal_muscle, kidney | pancreas, liver, skeletal_muscle, kidney, adipose_tissue | pancreas, liver, skeletal_muscle, kidney, adipose_tissue |
| `water_case_01_adh_osmolarity` | hypothalamus, pituitary, kidney | hypothalamus, pituitary, kidney | hypothalamus, pituitary, kidney |
| `electrolyte_case_01_aldosterone` | adrenal_gland, kidney | pancreas, adrenal_gland, skeletal_muscle, kidney | pancreas, adrenal_gland, skeletal_muscle, kidney |
| `stress_case_01_catecholamine` | hypothalamus, adrenal_gland, liver, skeletal_muscle | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, kidney, adipose_tissue | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, adipose_tissue |
| `pressure_case_01_raas_aldosterone` | adrenal_gland, kidney, lung | hypothalamus, pituitary, adrenal_gland, kidney, lung | hypothalamus, pituitary, adrenal_gland, kidney, lung |
| `stress_case_02_glucocorticoid` | hypothalamus, pituitary, adrenal_gland, adipose_tissue | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, kidney, adipose_tissue | hypothalamus, pituitary, pancreas, adrenal_gland, liver, skeletal_muscle, kidney, adipose_tissue |
| `growth_case_01_gh` | hypothalamus, pituitary, liver, skeletal_muscle, adipose_tissue | hypothalamus, pituitary, pancreas, liver, skeletal_muscle, adipose_tissue, bone | hypothalamus, pituitary, pancreas, liver, skeletal_muscle, adipose_tissue, bone |
| `calcium_case_01_pth` | kidney, small_intestine, parathyroid, bone | kidney, small_intestine, parathyroid, bone | kidney, small_intestine, parathyroid, bone, thyroid |
| `thyroid_case_01_tsh_feedback` | pituitary, thyroid | hypothalamus, pituitary, liver, skeletal_muscle, adipose_tissue, thyroid | hypothalamus, pituitary, liver, skeletal_muscle, adipose_tissue, thyroid |
| `calcium_case_02_calcitonin` | kidney, bone, thyroid | kidney, parathyroid, bone, thyroid | kidney, parathyroid, bone, thyroid |

## Core Conclusion

- Both models recover every required agent; over-selection is the main failure mode.
- Gemini 3.7 Flash does not improve selection quality over 3.8 Flash, but uses fewer tokens.
- The next Meta Agent iteration should increase precision without reducing recall.
