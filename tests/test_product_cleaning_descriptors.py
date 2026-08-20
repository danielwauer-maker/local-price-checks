from app.engine_v140.product_cleaning import product_name_issue


def test_rejects_descriptor_only_product_names():
    bad = [
        "100% pflanzlich",
        "16-18% Vol., versch. Sorten",
        "37,5% Vol. oder Razz 27% Vol.",
        "2er-Set",
        "3er-Set",
        "4er-Set",
        "Kl. II",
        "3-fach sortiert, geschnitten",
        "grillfertig gewürzt",
        "feine Würzung, vom Eifelschwein",
        "ohne Speckwürfel, leckere Würzung, vom Eifelschwein",
        "gegart, geschnitten, vom Eifelschwein",
        "grob oder fein, feine Würzung, vom Eifelschwein",
        "Peanut",
        "gegart",
        "je St.",
        "aus Rind- und Schweinefleisch, mit Käse",
        "vom Jungbullen, am Stück oder in Scheiben",
        "mit Silberzwiebeln verfeinert",
        "ohne Knochen",
        "in feiner Beize eingelegt",
        "für Grill & Pfanne",
        "cremiger Brotaufstrich",
        "Sorte: siehe Etikett, Kl. I",
        "„Aromatica“, Kl. I",
        "natur oder mariniert",
        "geschnitten, mittelfeine Körnung, vom Eifelschwein",
        "zart und mager",
        "Schnittkäse, mind. 50% Fett i.Tr.",
        "Nordische Art",
        "mittelscharf",
        "vorgekocht",
        "extra Ananas",
    ]
    for name in bad:
        assert product_name_issue(name), name


def test_keeps_real_product_names():
    good = [
        "Axe Bodyspray",
        "Bresso Feine Kräuter",
        "Oreo Double Creme",
        "Ehrmann Almighurt",
        "Müller Milch Reis",
        "Bifteki",
        "Mars m&m’s Peanut",
        "Ausgezogene Küchle",
        "schonend gegarte Schweinerippchen in Whiskey Marinade",
    ]
    for name in good:
        assert product_name_issue(name) is None, name
