"""
Sentiment analysis dictionary for Argentina - Gender balanced
Terms are balanced to maintain approximately 50/50 feminine and masculine references
or gender-neutral terms where possible.
"""

SENTIMIENTO_DICT = {
    "Menosprecio": [
        # Feminine-specific
        "Loca", "gauchita", "tonta", "minita", "pendeja",
        "vieja", "vaga", "mamarracha", "mentirosa", "drogadicta",
        "falopera", "cínica", "hipócrita", "nena", "nenita",
        "tontita", "hueca", "boludita", "lenta", "lerda",
        # Masculine-specific
        "boludo", "pelotudo", "forro", "inútil", "idiota",
        "imbécil", "ignorante", "inexperto", "mina", "chiquito",
        "mogólico", "lento", "lerdo",
        # Gender-neutral/shared
        "lacra", "villera", "negra", "grasa", "ignorante",
        "inexperta", "nada", "saber", "sabes", "chiqui"
    ],
    
    "Cuerpo y sexualidad": [
        # Feminine-specific
        "Puta", "turra", "trola", "petera", "gorda",
        "lesbiana", "trava", "frígida", "yegua", "fea",
        "conchuda", "concha", "tacos",
        # Masculine-specific
        "putazo", "pelotudo", "cornudo", "macho", "machista",
        "violador", "abusador", "predador",
        # Gender-neutral/shared
        "gato", "atorranta", "prostituta", "gauchita", "culo",
        "tetas", "escote", "amante", "chongo", "novio", "novia",
        "incogible"
    ],
    
    "Roles y género": [
        # Feminine-specific
        "Malamadre", "abandónica", "madre", "hijita", "hija",
        "descuidada", "descuidas", "abandonas", "mina",
        "infértil", "privada", "laburanta",
        # Masculine-specific
        "padre", "hijo", "macho", "marido", "irresponsable",
        "abandónico", "machista", "egoísta", "vago",
        # Gender-neutral/shared
        "platos", "cuidar", "cuida", "ocupate", "casa", "hijos",
        "hijes", "amante", "chongo", "novio", "novia", "nada",
        "saber", "sabes", "ignorante", "inexperta", "nena", "nenita",
        "minita", "tontita", "hueca", "hijas", "serví", "servir",
        "café", "mate", "criar", "crianza", "fértil", "egoísta",
        "hogar", "limpiar", "laburar", "labura", "trabar", "trabajas",
        "trabaja"
    ],
    
    "Amenazas": [
        # Violence/Physical harm
        "Matar", "muerta", "quemar", "quemada", "ahogar", "ahogada",
        "asfixia", "ahorcada", "golpear", "golpeada", "pegar", "romper",
        "dañar", "tirar", "chocar", "muertos",
        # Death/Loss-related
        "enviudar", "viuda", "desaparecer", "desaparecida", "secuestrar",
        "secuestrada",
        # Sexual violence
        "violación", "violar", "zanja", "coger", "penetrar", "tocar",
        "desnudar", "desnuda", "penetro", "violé", "violo",
        # Sexual harassment (threatening)
        "cojo", "chupo", "parto", "acaricio", "caricia", "acariciame",
        "pito", "pija", "pene", "chupala", "chupame",
        # Silencing/Control
        "callate", "deja de hablar", "callar", "silenciar", "silencio",
        "vigilar", "vigilamos", "vigilada", "vigilando", "viendo",
        # Economic threats
        "decís boludeces", "denunciar", "devolvé", "plata", "guita",
        "robar", "robaste", "malgastar"
    ],
    
    "Acoso": [
        # Appearance-focused
        "Hermosa", "Linda", "divina", "buena", "potra", "bárbara",
        "tetas", "culo", "cuerpo", "gorda", "flaca",
        # Intentions/Desires
        "querer", "quiero", "hago", "haceme", "acompañar",
        "acompañame", "gustar", "gustas",
        # Emotional manipulation
        "enamoré", "enamorar", "vida", "cariño", "cariños"
    ],
    
    "Desprestigio": [
        # Political labels (feminine)
        "Piquetera", "Montonera", "Troska", "Chorra", "Kuka",
        # Political labels (masculine)
        "Piquetero", "Montonero", "Chorro", "Kuky",
        # General accusations
        "Korrupta", "Corrupta", "Oportunista", "Ladrona", "Lacra",
        "Feminazi", "Abortera", "Deja de robar"
    ]
}

# Summary statistics
def print_statistics():
    for category, terms in SENTIMIENTO_DICT.items():
        print(f"\n{category}: {len(terms)} términos")
        print(f"  Muestra: {', '.join(terms[:5])}...")

if __name__ == "__main__":
    print_statistics()
