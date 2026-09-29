"""Small shared whitelist for rules that inspect SciPy hypothesis tests."""

SUPPORTED_SCIPY_TESTS = frozenset(
    {
        "scipy.stats.ttest_ind",
        "scipy.stats.ttest_rel",
        "scipy.stats.ttest_1samp",
        "scipy.stats.mannwhitneyu",
        "scipy.stats.wilcoxon",
        "scipy.stats.pearsonr",
        "scipy.stats.spearmanr",
        "scipy.stats.chi2_contingency",
        "scipy.stats.f_oneway",
    }
)
