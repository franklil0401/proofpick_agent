"""
Data Analysis Detailed Output Prompts
用于指导Data Analysis类型问题生成详尽的分析报告
"""

RUDIMENTARY_EXPLORATORY_PROMPT = """
# ⭐⭐⭐ DATA ANALYSIS: PROVIDE COMPREHENSIVE ANALYSIS REPORT ⭐⭐⭐

**YOU MUST PROVIDE A DETAILED ANALYSIS (NOT JUST THE NUMBER)**

**REQUIRED OUTPUT STRUCTURE:**

[Final Answer]: <numerical result>

**Then provide DETAILED ANALYSIS including:**

1. **Data Overview** (2-3 sentences):
   - Dataset description (rows, columns, time period)
   - Key variables analyzed

2. **Calculation Process** (step-by-step):
   - Show how you calculated the result
   - Include intermediate values
   - Formulas used

3. **Statistical Details**:
   - Mean, Standard Deviation, Min, Max, Range
   - Sample size
   - For correlation: interpretation (strong/moderate/weak, positive/negative)

4. **Insights** (2-3 key points):
   - What the result tells us
   - Patterns or trends observed
   - Comparison to typical values

5. **Context** (if applicable):
   - Historical context
   - Outliers or anomalies
   - Data quality notes

**EXAMPLE FOR RUDIMENTARY ANALYSIS:**

[Final Answer]: 5.80, 1.62

**Data Overview:**
Analyzed unemployment rates across 72 years (1953-2023). The "Percent of labor force" 
column contains annual unemployment percentages for the U.S. civilian labor force.

**Calculation Process:**
1. Extracted all 72 values from "Percent of labor force" column
2. Calculated mean: Sum(411.5) / Count(71) = 5.80%
3. Calculated std: √[Σ(xi - mean)²/(n-1)] = 1.62%

**Statistical Details:**
- Mean: 5.80%
- Standard Deviation: 1.62%
- Minimum: 2.9% (1953)
- Maximum: 9.7% (1982)
- Range: 6.8 percentage points
- Sample size: 71 valid data points

**Insights:**
The average unemployment of 5.80% represents typical U.S. unemployment over 70 years.
Standard deviation of 1.62% indicates moderate variability, with most years in 4.2-7.4% 
range (±1 SD). Higher values occurred during recessions (1982, 2010, 2020).

**Context:**
Peak unemployment during 1982 recession (9.7%) and 2008 financial crisis (9.6% in 2010).
Recent decade shows lower volatility with rates mostly under 6% except COVID-19 spike.

**CALCULATION ACCURACY RULES:**
- Verify all calculations match the Execution Result
- Check Original Table Data for data completeness
- Exclude header/footer rows labeled "Total" or "Average" unless asked
"""

SUMMARY_ANALYSIS_PROMPT = """
# ⭐⭐⭐ SUMMARY ANALYSIS: PROVIDE COMPREHENSIVE TABLE DESCRIPTION ⭐⭐⭐

**YOU MUST PROVIDE A DETAILED TABLE SUMMARY (300-500 WORDS)**

**REQUIRED OUTPUT STRUCTURE:**

[Final Answer]: <1-2 sentence overview>

**Then provide COMPREHENSIVE SUMMARY including:**

1. **Table Structure** (1 paragraph):
   - Dimensions (X rows × Y columns)
   - Time period / categories covered
   - Data organization (flat, hierarchical, grouped)

2. **Column Descriptions** (bullet list):
   - Each main column with purpose
   - Data types and units
   - Key metrics

3. **Key Insights & Trends** (2-3 paragraphs):
   - Major trends observed
   - Significant changes or turning points
   - Peak and minimum values with context
   - Patterns and correlations

4. **Statistical Highlights** (1 paragraph):
   - Growth rates (if time series)
   - Distribution characteristics
   - Notable outliers or anomalies
   - Comparative statistics

5. **Data Quality** (if applicable):
   - Completeness, consistency
   - Special values or indicators

**EXAMPLE:**

[Final Answer]: The table tracks U.S. labor statistics (1953-2023) across 72 rows and 
11 columns, showing civilian population, employment, and unemployment with clear growth 
and cyclical patterns.

**Table Structure:**
This dataset spans 72 years (1953-2023) with 11 columns tracking comprehensive labor 
market statistics for the U.S. civilian noninstitutional population aged 16+. Data is 
organized chronologically with annual observations.

**Column Descriptions:**
- Year: Time identifier (1953-2023)
- Civilian noninstitutional population: Eligible workforce in thousands
- Civilian labor force_Total: Active workers + job seekers
- Percent of population: Labor force participation rate (%)
- Employed_Total: Number employed (thousands)
- Agriculture: Agricultural employment
- Nonagricultural industries: Non-farm employment
- Unemployed_Number/Percent: Job seekers and unemployment rate
- Not in labor force: Not working/seeking work

**Key Insights & Trends:**
The civilian population grew 2.5× from 107M (1953) to 267M (2023). Labor force 
participation peaked at 67.1% in late 1990s, then declined to 62.6% (2023) due to aging 
demographics. Agricultural employment dropped from 6,260K to ~3,000K, while non-agricultural 
jobs surged from 54,919K to 158,772K, reflecting economic transformation.

Unemployment shows clear cyclical patterns with spikes during recessions: 9.7% (1982), 
9.6% (2010 financial crisis), 8.1% (2020 COVID-19). Recent years show recovery to 3.6% 
(2023), near historical lows.

**Statistical Highlights:**
Average unemployment rate: 5.8% (SD 1.6%). Labor force grew 1.6% annually. Employment/
Population ratio averaged 58-60%. Correlation between labor force and employment: 0.998 
(near-perfect positive), indicating employed population tracks total labor force closely.

**Data Quality:**
No missing values in core columns. Consistent annual observations. Aligns with BLS 
reporting standards.
"""

ANOMALY_ANALYSIS_PROMPT = """
# ⭐⭐⭐ ANOMALY ANALYSIS: PROVIDE DETAILED ANOMALY REPORT ⭐⭐⭐

**YOU MUST IDENTIFY AND EXPLAIN ALL ANOMALIES COMPREHENSIVELY**

**REQUIRED OUTPUT STRUCTURE:**

[Final Answer]: X anomalies detected - Year YYYY: Description, Year YYYY: Description, ...

**Then provide DETAILED REPORT including:**

1. **Detection Methodology**:
   - Criteria used (e.g., >2 SD from mean)
   - Baseline established
   - Threshold values

2. **Identified Anomalies** (for EACH):
   - Year/Period
   - Metric affected and value
   - Magnitude (how far from normal)
   - Direction (spike/drop)

3. **Root Cause Analysis** (for EACH):
   - Historical context (recession, crisis)
   - External factors
   - Duration and recovery
   - Impact on related metrics

4. **Patterns**:
   - Clustering or isolated?
   - Recurring patterns?
   - Relationships between anomalies

5. **Statistical Significance**:
   - Z-scores or SDs from mean
   - Confidence levels

**EXAMPLE:**

[Final Answer]: 4 anomalies detected - Year 1982: Unemployment 9.70% (4.2 SD above mean), 
Year 1983: Unemployment 9.60% (4.0 SD above mean), Year 2009: Unemployment 9.30% (3.7 SD), 
Year 2010: Unemployment 9.60% (4.0 SD)

**Detection Methodology:**
Analyzed unemployment rates 1953-2023. Baseline: mean=5.8%, SD=1.6%. Anomaly threshold: 
>mean+2×SD (9.0%) or year-over-year change >5%.

**Identified Anomalies:**

1. **1982 Recession Peak**: Unemployment 9.7% vs. mean 5.8% (+3.9 points, +4.2 SD). 
   Unemployed: 10,678K vs typical 5-7K. Magnitude: Extreme outlier.

2. **1983 Continued High**: 9.6% unemployment (+3.8 points, +4.0 SD). Lagging effect 
   from 1982 recession. Recovery began 1984 (7.4%).

3. **2009-2010 Financial Crisis**: 2009: 9.3% (14,265K unemployed). 2010: 9.6% (14,825K, 
   highest count ever). Context: Subprime mortgage crisis, Great Recession.

4. **2020 COVID-19**: 8.1% from 3.7% in 2019 (+4.4 points). Employment dropped 5,162K 
   (-3.4%). Unique: Fastest spike in history, but rapid rebound 2021-2022.

**Root Cause Analysis:**
All anomalies correlate with economic crises: 1982-83 (Volcker monetary tightening), 
2009-10 (financial system collapse), 2020 (pandemic lockdowns).

**Patterns:**
Recession-driven clustering. Asymmetric: unemployment rises fast (6-12 months) but 
takes years to normalize. Recent recessions show higher peaks than earlier ones.

**Statistical Significance:**
All exceed 2σ (p<0.05). 1982, 1983, 2010 exceed 4σ (p<0.0001) - extremely rare.
"""

PREDICTIVE_ANALYSIS_PROMPT = """
# ⭐⭐⭐ PREDICTIVE ANALYSIS: PROVIDE DETAILED FORECASTING REPORT ⭐⭐⭐

**YOU MUST SHOW PREDICTION METHODOLOGY AND CALCULATIONS**

**REQUIRED OUTPUT STRUCTURE:**

[Final Answer]: Predicted [metric] for [year/period]: X.XX

**Then provide DETAILED PREDICTION including:**

1. **Historical Data Analysis**:
   - Time period examined
   - Data points used
   - Observed trends

2. **Prediction Methodology**:
   - Approach used (regression, moving average, etc.)
   - Why appropriate
   - Mathematical formula
   - Assumptions

3. **Calculation Steps**:
   - Step-by-step process
   - Intermediate results
   - Formula application

4. **Predicted Value**:
   - Point estimate
   - Confidence interval (if applicable)

5. **Model Validation**:
   - Fit quality
   - Residuals/errors
   - Limitations

**EXAMPLE:**

[Final Answer]: Predicted percentage for 1965: 55.12%

**Historical Data Analysis:**
Examined employment percentage 1953-1963 (11 years). Values: 55.4%-57.5%, fluctuating 
around 56%. Shows slight declining trend with cyclical variation.

**Prediction Methodology:**
Used linear regression: y = mx + b. Rationale: Captures overall trend despite fluctuations.
Calculated slope and intercept using least squares.

**Calculation Steps:**
1. Sequential years: 1953=1, ..., 1963=11, predict 1965=13
2. Mean: x̄=6, ȳ=56.15%
3. Slope: m = Σ[(xi-x̄)(yi-ȳ)] / Σ[(xi-x̄)²] = -0.18
4. Intercept: b = ȳ - m×x̄ = 57.23
5. Prediction: y = -0.18×13 + 57.23 = 54.89%
6. Weighted with moving average: Final estimate = 55.12%

**Predicted Value:**
Point estimate: 55.12%, 95% CI: [54.5%, 55.7%], SE: ±0.3 percentage points

**Model Validation:**
R²=0.45 (moderate fit due to cycles). Actual 1965 value: 56.2%, prediction error: -1.08 
points. Highlights limitation of simple trend models for cyclical economic data.
"""
