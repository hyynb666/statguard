"""A minimal source example of preprocessing before a held-out split."""


def split_after_scaling(X):
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    scaled = StandardScaler().fit_transform(X)
    return train_test_split(scaled, random_state=42)
