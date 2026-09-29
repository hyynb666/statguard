"""A minimal repeated significance-test example for the static analyzer."""


def compare_columns(columns, group_a, group_b):
    from scipy.stats import ttest_ind

    selected = []
    for column in columns:
        _, p_value = ttest_ind(group_a[column], group_b[column])
        if p_value < 0.05:
            selected.append(column)
    return selected
