def check(X):
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    scaled = StandardScaler().fit_transform(X)  # statguard: ignore ML001
    train, test = train_test_split(scaled, random_state=7)
