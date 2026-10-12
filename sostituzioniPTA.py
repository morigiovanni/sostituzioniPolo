"""
Sostituzioni giornaliere - versione 3 (proposta automatica del supplente)

Novità rispetto alla v2:
- per ogni ora da coprire propone direttamente il supplente, con queste regole:
    1. un docente in compresenza nella classe (prima scelta assoluta);
    2. altrimenti un docente a disposizione della stessa sede
       (DISP_SEDE per le classi della sede, DISP_SUCC per la succursale), scegliendo:
         a. chi copre tutte le mezz'ore da coprire,
         b. chi fa parte del consiglio di classe,
         c. chi insegna la stessa disciplina (codice di concorso, es. A-12),
         d. chi ha il carico minore quel giorno (ore di lezione + supplenze già fatte);
    3. se non c'è nessuno libero scrive "SEDE" o "MORO" come prima;
- legge l'orario a mezz'ore (Lun._1_1, Lun._1_2, Lun._1_3, Lun._2_1 ...);
  il numero di ore del giorno si ricava dalle colonne (il sabato ne ha 4);
- in colonna E segnala le coperture parziali delle mezz'ore;
- consigli di classe e discipline sono letti dal foglio Google delle cattedre;
- prima di azzerare il foglio può registrare le supplenze della giornata nel
  foglio "Registro supplenze" del file cattedre (con l'indicazione "eccedente"),
  e il numero di supplenze fatte nell'anno entra nella scelta a parità di carico;
- se non resta nessun docente a disposizione, propone un docente che si è reso
  disponibile alle ore eccedenti (modulo Google), scrivendo "(eccedente)":
    a. chi copre tutte le mezz'ore,
    b. chi non ha la cattedra completa (meno di 18 ore),
    c. chi ha fatto meno eccedenti oggi (massimo MAX_ECCEDENTI_GIORNO al giorno),
    d. chi ha fatto meno eccedenti nell'anno.

Avvio:  streamlit run sostituzioniPTA_v3.py
"""
import os
import re
from datetime import date, datetime
from collections import Counter, defaultdict

import gspread
import numpy as np
import pandas as pd
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

# ----------------------------------------------------------------------------
# Configurazione
# ----------------------------------------------------------------------------
CARTELLA = os.path.dirname(os.path.abspath(__file__))
FILE_CREDENZIALI = os.path.join(CARTELLA, "progettoorariopython-1dcdbcf2aabc.json")
# ID del foglio Google delle cattedre: è la parte dell'indirizzo tra /d/ e /edit
ID_CATTEDRE = "1t2B54aBo8FBnsnKdUmtz4l1stqChKvv5qH_YSKzoDSY"
FOGLIO_CATTEDRE = "Foglio1"
# ID del foglio con le risposte del modulo "Disponibilità eccedenti"
ID_ECCEDENTI = "1L3XrvjPpAEi6ROYWIvmGO1OcvU6zkzOnbNFBRUdmePw"
MAX_ECCEDENTI_GIORNO = 2
ORE_CATTEDRA_COMPLETA = 18
FOGLIO_REGISTRO = "Registro supplenze"        # creato in automatico nel file cattedre
INTESTAZIONE_REGISTRO = ["Data", "Giorno", "Ora", "Classe", "Assente",
                         "Supplente", "Eccedente", "Note"]
ID_ORARIO = "1_cQYfdXj0IQNClKJf8SUpvaVU-tuOiGnWc6r8zGH134"
ID_SOSTITUZIONI = "1WtRNOWubgWlJhnyc2YzYGb9IJpe-Zne7w8vWC6E7Al0"
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

CLASSI_SEDE = ["1A-AFM", "2A-AFM", "3A-AFM", "4A-AFM", "5A-AFM", "2C-AFM", "2B-AFM",
               "5L-RIM", "5L-AFM", "3F-SIA", "3L-RIM", "4F-SIA", "5F-SIA", "5L-AFM, 5L-RIM",
               "1C-AFM", "1B-AFM", "4L-RIM", "3G-SIA, 3G-AFM", "3G-SIA", "3G-AFM"]
DISP_SEDE, DISP_SUCC = "DISP_SEDE", "DISP_SUCC"
DISPONIBILITA = (DISP_SEDE, DISP_SUCC)
SEGNAPOSTO = ("SEDE", "MORO")

GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab"]
BLOCCHI = [1, 2, 3, 4, 5]
INIZIO_BLOCCO = {1: 4, 2: 17, 3: 30, 4: 43, 5: 56}  # prima riga di ogni ora nel foglio
RIGHE_PER_BLOCCO = 13
AREA_SOSTITUZIONI = "B4:E68"

# Colonne del foglio sostituzioni
COL_CLASSE, COL_ASSENTE, COL_SUPPLENTE, COL_NOTE = 2, 3, 4, 5   # B, C, D, E
COL_DISP_SUCC, COL_DISP_SEDE = 6, 7                              # F, G
COL_CONTATORI = 8                                                # H1:H5
CELLA_DATA = (6, 8)                                              # H6: data della giornata nel foglio
FORMATO_DATA = "%d/%m/%Y"


# ----------------------------------------------------------------------------
# Utilità su nomi, classi e mezz'ore
# ----------------------------------------------------------------------------
def norm_nome(nome):
    """Confronto dei nomi senza badare a maiuscole e spazi."""
    return " ".join(str(nome).split()).casefold()


def pulisci_supplente(testo):
    """
    Toglie dal nome tutto ciò che è tra parentesi e riconosce le indicazioni:
    'Rossi Mario (aula magna, eccedente)' -> ('Rossi Mario', eccedente=True, aula_magna=True)
    """
    testo = str(testo or "")
    tra_parentesi = " ".join(re.findall(r"\((.*?)\)", testo)).lower()
    eccedente = "eccedent" in tra_parentesi
    aula_magna = bool(re.search(r"aula\s*magna", tra_parentesi))
    return re.sub(r"\(.*?\)", "", testo).strip(), eccedente, aula_magna


def parti_classe(testo):
    """'5L-AFM, 5L-RIM' -> {'5L-AFM', '5L-RIM'};  '3n-inf' -> {'3N-INF'}"""
    return {p.strip().upper().replace(" ", "") for p in str(testo).split(",") if p.strip()}


def _prefisso(classe):
    return classe.split("-")[0]


def stessa_classe(classi_docente, cla):
    """True se il docente ha in cattedra almeno una parte della classe `cla`."""
    for parte in parti_classe(cla):
        for c in classi_docente:
            if c == parte or ("-" not in c and c == _prefisso(parte)):
                return True
    return False


def descrivi_mezzore(mezzore):
    return "-".join(f"{m}ª" for m in sorted(mezzore)) + " mezz'ora"


def colonne_ora(orario, giorno, ora):
    """Colonne delle mezz'ore di un'ora, es. {1: 'Lun._1_1', 2: 'Lun._1_2', 3: 'Lun._1_3'}"""
    schema = re.compile(rf"^{re.escape(giorno)}\._{ora}_(\d+)$")
    col = {}
    for c in orario.columns:
        m = schema.match(str(c))
        if m:
            col[int(m.group(1))] = c
    return dict(sorted(col.items()))


def ore_del_giorno(orario, giorno):
    schema = re.compile(rf"^{re.escape(giorno)}\._(\d+)_\d+$")
    ore = {int(m.group(1)) for c in orario.columns if (m := schema.match(str(c)))}
    return [o for o in sorted(ore) if o in INIZIO_BLOCCO]


def valore(orario_idx, docente, colonna):
    v = orario_idx.at[docente, colonna] if docente in orario_idx.index else np.nan
    return None if pd.isna(v) or str(v).strip() == "" else str(v).strip()


# ----------------------------------------------------------------------------
# Lettura delle cattedre
# ----------------------------------------------------------------------------
def _numero(x):
    try:
        float(str(x).replace(",", "."))
        return str(x).strip() != ""
    except ValueError:
        return False


def _vuoto(x):
    return x is None or str(x).strip() == ""


def leggi_cattedre(righe):
    """
    `righe`: le righe del foglio cattedre (liste di valori, come da get_all_values).
    Restituisce {nome_normalizzato: {"classi": set, "discipline": set, "ore": numero o None}}.
    Le ore sono la somma delle righe di totale (es. "18", "15+3") di tutte le
    discipline del docente. Usa solo le colonne A-F (Ipotesi A).
    """
    cattedre = defaultdict(lambda: {"classi": set(), "discipline": set(), "ore": None})
    disciplina, docente = None, None

    for riga in righe:
        a, b, c, d, e, f = (list(riga) + [None] * 6)[:6]
        if not _vuoto(a) and str(a).strip().upper().startswith("DISCIPLINA"):
            m = re.search(r"DISCIPLINA:\s*([A-Z]{1,2}-?\d+)", str(a).upper())
            disciplina = m.group(1) if m else str(a).strip()
            docente = None
            continue
        if _numero(a):                             # riga di inizio di un docente
            docente = None if _vuoto(f) else norm_nome(f)
            if docente and disciplina:
                cattedre[docente]["discipline"].add(disciplina)
        if docente is None:
            continue
        if not _vuoto(b):                          # riga con una classe
            sezione = str(b).strip().upper()
            indirizzi = [re.sub(r"\d+$", "", p.strip()).upper()
                         for p in str(c or "").split("_") if p.strip()]
            if indirizzi:
                for ind in indirizzi:
                    cattedre[docente]["classi"].add(f"{sezione}-{ind}")
            else:
                cattedre[docente]["classi"].add(sezione)
        elif not _numero(a) and not _vuoto(d) and _vuoto(e):
            numeri = re.findall(r"\d+(?:[.,]\d+)?", str(d))  # riga del totale: "18", "15+3"
            if numeri:
                ore = sum(float(n.replace(",", ".")) for n in numeri)
                cattedre[docente]["ore"] = (cattedre[docente]["ore"] or 0) + ore
            docente = None                         # fine del docente
    return dict(cattedre)


# ----------------------------------------------------------------------------
# Disponibilità alle ore eccedenti (risposte del modulo Google)
# ----------------------------------------------------------------------------
NUMERI_ORA = {"prima": 1, "seconda": 2, "terza": 3, "quarta": 4, "quinta": 5, "sesta": 6}


def leggi_eccedenti(righe):
    """
    `righe`: risposte del modulo (get_all_values), prima riga = intestazione.
    Restituisce {(cognome, nome): {(giorno, ora), ...}}; se una persona ha
    risposto più volte vale l'ultima risposta.
    """
    if not righe:
        return {}
    intestazione = [str(x).strip().lower() for x in righe[0]]
    col_cognome = next((i for i, x in enumerate(intestazione) if x.startswith("cognome")), None)
    col_nome = next((i for i, x in enumerate(intestazione) if x == "nome" or x.startswith("nome ")), None)
    col_ore = {}
    for i, x in enumerate(intestazione):
        m = re.search(r"\[(\w+)\s+ora\]", x)
        if m and m.group(1) in NUMERI_ORA:
            col_ore[i] = NUMERI_ORA[m.group(1)]
    if col_cognome is None or col_nome is None:
        return {}

    risposte = {}
    for r in righe[1:]:
        r = list(r) + [""] * len(intestazione)
        cognome, nome = r[col_cognome].strip(), r[col_nome].strip()
        if not cognome:
            continue
        disponibile = set()
        for i, ora in col_ore.items():
            for g in str(r[i]).split(","):
                g = g.strip()[:3].capitalize()
                if g in GIORNI:
                    disponibile.add((g, ora))
        risposte[(cognome, nome)] = disponibile
    return risposte


def abbina_eccedenti(docenti_orario, risposte):
    """
    Collega i nomi dell'orario alle risposte del modulo.
    Prova "Cognome Nome", "Nome Cognome", poi "Cognome N." e infine il solo cognome
    (se non è ambiguo). Restituisce ({nome_normalizzato_orario: disponibilità}, [non abbinati]).
    """
    abbinati, non_abbinati = {}, []
    chiavi = {norm_nome(d): d for d in docenti_orario}
    cognomi_orario = Counter()
    for k in chiavi:
        cognomi_orario[k.split(" ")[0]] += 1
    cognomi_modulo = Counter(norm_nome(c) for c, _ in risposte)

    for (cognome, nome), disp in risposte.items():
        c, n = norm_nome(cognome), norm_nome(nome)
        tentativi = [f"{c} {n}", f"{n} {c}"]
        trovato = next((t for t in tentativi if t in chiavi), None)
        if trovato is None and n:
            iniziale = [k for k in chiavi if k.startswith(f"{c} {n[0]}")]
            trovato = iniziale[0] if len(iniziale) == 1 else None
        if trovato is None and c in chiavi and cognomi_modulo[c] == 1:
            trovato = c
        if trovato is None:
            non_abbinati.append(f"{cognome} {nome}".strip())
        else:
            abbinati[trovato] = disp
    return abbinati, non_abbinati


# ----------------------------------------------------------------------------
# Scelta del supplente (non dipende da Streamlit né da Google: si prova da sola)
# ----------------------------------------------------------------------------
class Pianificatore:
    """
    Tiene lo stato della giornata (chi è già impegnato, quante supplenze ha fatto
    ciascuno) e calcola le sostituzioni.
    """

    def __init__(self, orario, giorno, cattedre, contatori,
                 gia_scritte=(), assenti_giorno=(), assenti_ore=None, supplenze_anno=None,
                 eccedenti_disponibili=None, eccedenti_anno=None):
        self.orario = orario
        self.idx = orario.dropna(subset=["DOCENTE"]).drop_duplicates("DOCENTE").set_index("DOCENTE")
        self.giorno = giorno
        self.cattedre = cattedre
        self.contatori = dict(contatori)
        self.ore = ore_del_giorno(orario, giorno)
        self.docenti = [d for d in orario["DOCENTE"].dropna().astype(str)]
        self.supplenze_anno = Counter(supplenze_anno or {})   # nome normalizzato -> n.
        self.eccedenti_disponibili = eccedenti_disponibili or {}  # nome norm. -> {(giorno, ora)}
        self.eccedenti_anno = Counter(eccedenti_anno or {})
        self.eccedenti_oggi = Counter()

        # esclusi: chi è assente tutto il giorno, o assente in certe ore
        self.assenti_giorno = {norm_nome(d) for d in assenti_giorno}
        self.assenti_ore = defaultdict(set)
        for ora, nomi in (assenti_ore or {}).items():
            self.assenti_ore[ora] |= {norm_nome(d) for d in nomi}

        # supplenze già scritte nel foglio oggi: (ora, assente, supplente)
        self.impegnati = defaultdict(set)     # ora -> supplenti già usati
        self.supplenze_fatte = Counter()
        for ora, assente, supplente in gia_scritte:
            supplente, eccedente, _ = pulisci_supplente(supplente)
            if assente:
                self.assenti_giorno.add(norm_nome(assente))
            if supplente and supplente not in SEGNAPOSTO:
                k = norm_nome(supplente)
                if k not in self.impegnati[ora]:      # aula magna: due classi = una sola ora
                    self.supplenze_fatte[k] += 1
                    if eccedente:
                        self.eccedenti_oggi[k] += 1
                self.impegnati[ora].add(k)

        self.lezioni = {norm_nome(d): self._ore_di_lezione(d) for d in self.docenti}

    # -- informazioni sui docenti ---------------------------------------------
    def _ore_di_lezione(self, docente):
        n = 0
        for ora in self.ore:
            vals = [valore(self.idx, docente, c) for c in colonne_ora(self.orario, self.giorno, ora).values()]
            if any(v and v not in DISPONIBILITA for v in vals):
                n += 1
        return n

    def carico(self, docente):
        k = norm_nome(docente)
        return self.lezioni.get(k, 0) + self.supplenze_fatte[k]

    def info(self, docente):
        return self.cattedre.get(norm_nome(docente), {"classi": set(), "discipline": set()})

    def libero(self, docente, ora):
        k = norm_nome(docente)
        return (k not in self.assenti_giorno and k not in self.assenti_ore[ora]
                and k not in self.impegnati[ora])

    def mancanti_in_cattedre(self):
        return sorted(d for d in self.docenti if norm_nome(d) not in self.cattedre)

    # -- scelta -----------------------------------------------------------------
    def _copertura(self, docente, colonne, mezzore, atteso):
        return {m for m in mezzore if valore(self.idx, docente, colonne[m]) == atteso}

    def scegli(self, assente, cla, ora, colonne, mezzore):
        """Restituisce (supplente, mezz'ore coperte, motivo)."""
        # 1. compresente
        compresenti = []
        for d in self.docenti:
            if norm_nome(d) == norm_nome(assente) or not self.libero(d, ora):
                continue
            cop = self._copertura(d, colonne, mezzore, cla)
            if cop:
                compresenti.append((-len(cop), d, cop))
        if compresenti:
            _, d, cop = min(compresenti)
            return d, cop, "compresente", False

        # 2. docenti a disposizione nella stessa sede
        tipo = DISP_SEDE if parti_classe(cla) & set().union(*map(parti_classe, CLASSI_SEDE)) else DISP_SUCC
        disc_assente = self.info(assente)["discipline"]
        candidati = []
        for d in self.docenti:
            if not self.libero(d, ora):
                continue
            cop = self._copertura(d, colonne, mezzore, tipo)
            if not cop:
                continue
            info = self.info(d)
            consiglio = stessa_classe(info["classi"], cla)
            materia = bool(disc_assente & info["discipline"])
            completo = cop == set(mezzore)
            chiave = (not completo, not consiglio, not materia, self.carico(d),
                      self.supplenze_anno[norm_nome(d)], d)
            candidati.append((chiave, d, cop, consiglio, materia))
        if candidati:
            chiave, d, cop, consiglio, materia = min(candidati)
            motivi = [m for m, ok in (("consiglio di classe", consiglio),
                                      ("stessa disciplina", materia)) if ok]
            motivi.append(f"carico {chiave[3]}, {chiave[4]} supplenze nell'anno")
            return d, cop, ", ".join(motivi), False

        # 3. docenti disponibili alle ore eccedenti
        scelta = self._scegli_eccedente(ora, colonne, mezzore)
        if scelta:
            return scelta

        # 4. nessuno libero
        return ("SEDE" if tipo == DISP_SEDE else "MORO"), set(), "nessun docente libero", False

    def _scegli_eccedente(self, ora, colonne, mezzore):
        candidati = []
        for d in self.docenti:
            k = norm_nome(d)
            if (self.giorno, ora) not in self.eccedenti_disponibili.get(k, set()):
                continue
            if not self.libero(d, ora) or self.eccedenti_oggi[k] >= MAX_ECCEDENTI_GIORNO:
                continue
            libere = {m for m in mezzore if valore(self.idx, d, colonne[m]) is None}
            if not libere:
                continue
            ore_catt = self.info(d).get("ore")
            incompleta = ore_catt is not None and ore_catt < ORE_CATTEDRA_COMPLETA
            chiave = (libere != set(mezzore), not incompleta, self.eccedenti_oggi[k],
                      self.eccedenti_anno[k], d)
            candidati.append((chiave, d, libere, ore_catt))
        if not candidati:
            return None
        chiave, d, libere, ore_catt = min(candidati)
        motivi = ["eccedente"]
        if ore_catt is not None:
            motivi.append(f"cattedra {ore_catt:g} ore")
        motivi.append(f"{chiave[2]} eccedenti oggi, {chiave[3]} nell'anno")
        return d, libere, ", ".join(motivi), True

    def sostituisci(self, docente, ore):
        """Celle da scrivere e riepilogo per le ore di assenza di `docente`."""
        celle, riepilogo = [], []
        for ora in ore:
            if ora not in self.ore:
                continue
            colonne = colonne_ora(self.orario, self.giorno, ora)
            # classi da coprire in quest'ora e relative mezz'ore
            da_coprire = defaultdict(set)
            for m, col in colonne.items():
                v = valore(self.idx, docente, col)
                if v and v not in DISPONIBILITA:
                    da_coprire[v].add(m)

            for cla, mezzore in da_coprire.items():
                supplente, coperte, motivo, eccedente = self.scegli(docente, cla, ora, colonne, mezzore)
                if supplente not in SEGNAPOSTO:
                    k = norm_nome(supplente)
                    self.impegnati[ora].add(k)
                    self.supplenze_fatte[k] += 1
                    if eccedente:
                        self.eccedenti_oggi[k] += 1
                        self.eccedenti_anno[k] += 1
                        supplente = f"{supplente} (eccedente)"

                note = []
                if mezzore != set(colonne):
                    note.append(f"lezione solo {descrivi_mezzore(mezzore)}")
                if coperte and coperte != mezzore:
                    note.append(f"supplente solo {descrivi_mezzore(coperte)}")
                nota = "; ".join(note)

                riga = INIZIO_BLOCCO[ora] + self.contatori[ora]
                celle += [(riga, COL_CLASSE, cla), (riga, COL_ASSENTE, docente),
                          (riga, COL_SUPPLENTE, supplente), (riga, COL_NOTE, nota)]
                self.contatori[ora] += 1
                celle.append((ora, COL_CONTATORI, self.contatori[ora]))
                riepilogo.append({"Ora": ora, "Classe": cla, "Assente": docente,
                                  "Supplente": supplente, "Note": nota, "Motivo": motivo})
        return celle, riepilogo

    def elenco_disponibili(self, ora, tipo):
        """Docenti a disposizione in quell'ora, con le mezz'ore se parziali."""
        colonne = colonne_ora(self.orario, self.giorno, ora)
        righe = []
        for d in self.docenti:
            cop = self._copertura(d, colonne, list(colonne), tipo)
            if cop:
                righe.append(d if cop == set(colonne) else f"{d} ({descrivi_mezzore(cop)})")
        return "\n".join(righe)


# ----------------------------------------------------------------------------
# Accesso a Google Sheets e al file cattedre
# ----------------------------------------------------------------------------
@st.cache_resource
def client_google():
    """
    Su Streamlit Cloud usa le credenziali salvate nei Secrets ([gcp_service_account]);
    sul computer usa il file .json nella cartella del programma.
    """
    try:
        dati = dict(st.secrets["gcp_service_account"])
    except Exception:
        dati = None
    if dati:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dati, SCOPE)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name(FILE_CREDENZIALI, SCOPE)
    return gspread.authorize(creds)


@st.cache_data(ttl=600)
def carica_orario():
    foglio = client_google().open_by_key(ID_ORARIO).get_worksheet(0)
    orario = pd.DataFrame(foglio.get_all_records())
    with pd.option_context("future.no_silent_downcasting", True):
        return orario.replace("", np.nan).infer_objects()


@st.cache_data(ttl=600)
def carica_cattedre():
    libro = client_google().open_by_key(ID_CATTEDRE)
    try:
        foglio = libro.worksheet(FOGLIO_CATTEDRE)
    except gspread.exceptions.WorksheetNotFound:
        foglio = libro.get_worksheet(0)
    return leggi_cattedre(foglio.get_all_values())


def apri_registro(crea=False):
    libro = client_google().open_by_key(ID_CATTEDRE)
    try:
        return libro.worksheet(FOGLIO_REGISTRO)
    except gspread.exceptions.WorksheetNotFound:
        if not crea:
            return None
        ws = libro.add_worksheet(FOGLIO_REGISTRO, rows=1000, cols=len(INTESTAZIONE_REGISTRO))
        ws.append_row(INTESTAZIONE_REGISTRO, value_input_option="RAW")
        return ws


@st.cache_data(ttl=600)
def carica_registro():
    ws = apri_registro()
    return ws.get_all_values() if ws else []


def conta_registro(righe):
    """Da righe del registro a {nome_normalizzato: (nome, totale, eccedenti)}."""
    tot, ecc, nomi = Counter(), Counter(), {}
    for r in righe[1:]:
        r = list(r) + [""] * len(INTESTAZIONE_REGISTRO)
        nome = r[5].strip()
        if not nome or nome in SEGNAPOSTO:
            continue
        k = norm_nome(nome)
        nomi.setdefault(k, nome)
        tot[k] += 1
        if r[6].strip().lower() in ("sì", "si", "x", "true"):
            ecc[k] += 1
    return {k: (nomi[k], tot[k], ecc[k]) for k in tot}


def giorno_di(data):
    return (GIORNI + ["Dom"])[data.weekday()]


def righe_giornata(righe_foglio, data):
    """
    Righe del foglio sostituzioni (B4:E68) -> righe per il registro.
    Se lo stesso docente compare più volte nella stessa ora (classi riunite in
    aula magna) diventa una sola riga, quindi una sola ora di supplenza:
    classi e assenti vengono uniti con " + ".
    """
    uscita, unite = [], {}            # (ora, nome normalizzato) -> riga già in uscita
    for i, r in enumerate(righe_foglio):
        riga_foglio = 4 + i
        ora = next((o for o in BLOCCHI
                    if INIZIO_BLOCCO[o] <= riga_foglio < INIZIO_BLOCCO[o] + RIGHE_PER_BLOCCO), None)
        r = [str(x) for x in list(r) + [""] * 4]
        classe, assente, supplente, nota = (x.strip() for x in r[:4])
        if not ora or not assente:
            continue
        nome, eccedente, aula_magna = pulisci_supplente(supplente)
        chiave = (ora, norm_nome(nome))
        if nome and nome not in SEGNAPOSTO and chiave in unite:
            riga = unite[chiave]
            riga[3] += f" + {classe}"
            riga[4] += f" + {assente}"
            if eccedente:
                riga[6] = "Sì"
            if "aula magna" not in riga[7]:
                riga[7] = "; ".join(x for x in ("aula magna", riga[7]) if x)
            if nota and nota not in riga[7]:
                riga[7] += f"; {nota}"
            continue
        note = "; ".join(x for x in ("aula magna" if aula_magna else "", nota) if x)
        riga = [data.strftime(FORMATO_DATA), giorno_di(data), str(ora), classe,
                assente, nome, "Sì" if eccedente else "", note]
        uscita.append(riga)
        if nome and nome not in SEGNAPOSTO:
            unite[chiave] = riga
    return uscita


def registra_giornata(sh, data, sovrascrivi=False):
    """
    Copia le supplenze del foglio nel registro annuale.
    Restituisce (righe scritte, righe già presenti per quella data);
    righe scritte è None se la data c'era già e non si è chiesto di sovrascrivere.
    """
    ws = apri_registro(crea=True)
    valori = ws.get_all_values()
    testo_data = data.strftime(FORMATO_DATA)
    gia = [r for r in valori[1:] if r and r[0] == testo_data]
    if gia and not sovrascrivi:
        return None, len(gia)
    nuove = righe_giornata(sh.get(AREA_SOSTITUZIONI), data)
    if gia:
        restano = [valori[0]] + [r for r in valori[1:] if not (r and r[0] == testo_data)]
        ws.clear()
        ws.update(restano + nuove, "A1", value_input_option="RAW")
    elif nuove:
        ws.append_rows(nuove, value_input_option="RAW")
    carica_registro.clear()
    return len(nuove), len(gia)


def leggi_data_giornata(sh):
    try:
        return datetime.strptime(sh.cell(*CELLA_DATA).value or "", FORMATO_DATA).date()
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=600)
def carica_eccedenti():
    foglio = client_google().open_by_key(ID_ECCEDENTI).get_worksheet(0)
    return leggi_eccedenti(foglio.get_all_values())


def foglio_sostituzioni():
    return client_google().open_by_key(ID_SOSTITUZIONI).get_worksheet(0)


def leggi_stato_foglio(sh):
    """Contatori H1:H5 e supplenze già scritte nel foglio (ora, assente, supplente)."""
    valori = sh.get("H1:H5")
    contatori = {}
    for i, ora in enumerate(BLOCCHI):
        try:
            contatori[ora] = int(valori[i][0])
        except (IndexError, ValueError, TypeError):
            contatori[ora] = 0

    righe = sh.get(AREA_SOSTITUZIONI)
    gia_scritte = []
    for i, r in enumerate(righe):
        riga_foglio = 4 + i
        ora = next((o for o in BLOCCHI
                    if INIZIO_BLOCCO[o] <= riga_foglio < INIZIO_BLOCCO[o] + RIGHE_PER_BLOCCO), None)
        r = list(r) + [""] * 4
        if ora and r[1]:
            gia_scritte.append((ora, r[1], r[2]))
    return contatori, gia_scritte


def scrivi_celle(sh, celle):
    if celle:
        sh.update_cells([gspread.Cell(r, c, v) for r, c, v in celle])


def azzera_giornata(sh, pianificatore, data):
    sh.batch_clear([AREA_SOSTITUZIONI, "F4:G68", "H1:H5"])
    celle = [(ora, COL_CONTATORI, 0) for ora in BLOCCHI]
    celle.append((*CELLA_DATA, data.strftime(FORMATO_DATA)))
    for ora in pianificatore.ore:
        celle.append((INIZIO_BLOCCO[ora], COL_DISP_SUCC, pianificatore.elenco_disponibili(ora, DISP_SUCC)))
        celle.append((INIZIO_BLOCCO[ora], COL_DISP_SEDE, pianificatore.elenco_disponibili(ora, DISP_SEDE)))
    scrivi_celle(sh, celle)


def esegui_e_mostra(sh, orario, cattedre, giorno, richieste, assenti_giorno=(), assenti_ore=None):
    contatori, gia_scritte = leggi_stato_foglio(sh)
    try:
        registro = conta_registro(carica_registro())
    except Exception:
        registro = {}
    # supplenze "ordinarie" (non eccedenti) e eccedenti dell'anno, separate
    anno = {k: tot - ecc for k, (_, tot, ecc) in registro.items()}
    ecc_anno = {k: ecc for k, (_, tot, ecc) in registro.items()}
    try:
        ecc_disp, _ = abbina_eccedenti(orario["DOCENTE"].dropna().astype(str), carica_eccedenti())
    except Exception:
        ecc_disp = {}
        st.warning("Non riesco a leggere il foglio delle disponibilità alle ore eccedenti: "
                   "non verranno proposti docenti eccedenti.")
    p = Pianificatore(orario, giorno, cattedre, contatori, gia_scritte,
                      assenti_giorno=assenti_giorno, assenti_ore=assenti_ore,
                      supplenze_anno=anno, eccedenti_disponibili=ecc_disp,
                      eccedenti_anno=ecc_anno)
    tutte_celle, riepilogo = [], []
    for ora in p.ore:                       # ora per ora, così i supplenti non si sovrappongono
        for docente, ore in richieste:
            if ora in ore:
                celle, righe = p.sostituisci(docente, [ora])
                tutte_celle += celle
                riepilogo += righe
    scrivi_celle(sh, tutte_celle)

    pieni = [ora for ora in BLOCCHI if p.contatori[ora] > RIGHE_PER_BLOCCO]
    if pieni:
        st.warning(f"Attenzione: il blocco delle ore {pieni} ha superato "
                   f"{RIGHE_PER_BLOCCO} righe e sta invadendo l'ora successiva.")
    if riepilogo:
        st.success("Sostituzioni scritte sul foglio.")
        st.dataframe(pd.DataFrame(riepilogo), hide_index=True)
    else:
        st.info("Nessuna ora di lezione da coprire per la selezione fatta.")


# ----------------------------------------------------------------------------
# Interfaccia
# ----------------------------------------------------------------------------
def main():
    st.title("Sostituzioni giornaliere")

    orario = carica_orario()
    sh = foglio_sostituzioni()
    elenco_docenti = orario["DOCENTE"].dropna().tolist()

    try:
        cattedre = carica_cattedre()
    except Exception as errore:
        cattedre = {}
        st.warning("Non riesco a leggere il foglio delle cattedre "
                   f"({type(errore).__name__}): la scelta non terrà conto di "
                   "consiglio di classe e disciplina. Controlla ID_CATTEDRE e che il "
                   "foglio sia condiviso con l'account di servizio.")

    giorno = st.pills("Giorno?", GIORNI)
    if not giorno:
        st.info("Seleziona il giorno per iniziare.")
        st.stop()
    ore_giorno = ore_del_giorno(orario, giorno)

    try:
        _, non_abbinati = abbina_eccedenti(orario["DOCENTE"].dropna().astype(str), carica_eccedenti())
    except Exception:
        non_abbinati = []
    if non_abbinati:
        with st.expander(f"⚠️ {len(non_abbinati)} risposte del modulo eccedenti non abbinate all'orario"):
            st.write("Questi docenti non verranno proposti per le ore eccedenti finché il nome "
                     "non corrisponde a quello dell'orario.")
            st.write(", ".join(non_abbinati))

    mancanti = Pianificatore(orario, giorno, cattedre, {o: 0 for o in BLOCCHI}).mancanti_in_cattedre()
    if cattedre and mancanti:
        with st.expander(f"⚠️ {len(mancanti)} docenti dell'orario non trovati nel file cattedre"):
            st.write("Per loro consiglio di classe e disciplina non vengono considerati. "
                     "Controlla che il nome sia scritto uguale nei due file.")
            st.write(", ".join(mancanti))

    with st.expander("Nuova giornata: registra e azzera il foglio"):
        registra = st.checkbox("Prima registra le supplenze del foglio nel registro annuale",
                               value=True)
        if registra:
            data_reg = st.date_input("Data delle supplenze da registrare",
                                     value=leggi_data_giornata(sh) or date.today(),
                                     format="DD/MM/YYYY")
            st.caption("Vengono registrate le righe del foglio così come sono adesso, "
                       "comprese le tue modifiche a mano. Per le ore a pagamento scrivi "
                       "(eccedente) accanto al nome del supplente.")
            sovrascrivi = st.checkbox("Se questa data è già nel registro, sostituisci le sue righe")

        nuova_data = st.date_input("Data della nuova giornata", value=date.today(),
                                   format="DD/MM/YYYY")
        if giorno_di(nuova_data) != giorno:
            st.warning(f"Il {nuova_data.strftime(FORMATO_DATA)} è {giorno_di(nuova_data)}, "
                       f"ma hai selezionato {giorno}.")
        st.write("Poi cancella il foglio sostituzioni, azzera i contatori e scrive "
                 f"i docenti a disposizione di **{giorno}**.")
        conferma = st.checkbox("Sì, voglio cancellare tutto")
        if st.button("Registra e azzera" if registra else "Azzera il foglio",
                     disabled=not conferma, type="primary"):
            if registra:
                scritte, gia = registra_giornata(sh, data_reg, sovrascrivi)
                if scritte is None:
                    st.error(f"Il {data_reg.strftime(FORMATO_DATA)} è già nel registro "
                             f"({gia} righe). Il foglio NON è stato azzerato: spunta "
                             "'sostituisci' se vuoi aggiornarlo.")
                    st.stop()
                st.success(f"Registrate {scritte} supplenze del {data_reg.strftime(FORMATO_DATA)}"
                           + (f" (sostituite {gia} righe precedenti)." if gia else "."))
            azzera_giornata(sh, Pianificatore(orario, giorno, cattedre, {o: 0 for o in BLOCCHI}),
                            nuova_data)
            st.success(f"Foglio azzerato e disponibilità di {giorno} scritte.")

    with st.expander("Riepilogo annuale delle supplenze"):
        try:
            conteggi = conta_registro(carica_registro())
        except Exception as errore:
            conteggi = None
            st.warning(f"Non riesco a leggere il registro ({type(errore).__name__}).")
        if conteggi:
            tabella = pd.DataFrame(
                [{"Docente": n, "Supplenze": t, "Di cui eccedenti": e} for n, t, e in conteggi.values()]
            ).sort_values(["Supplenze", "Docente"], ascending=[False, True])
            st.dataframe(tabella, hide_index=True)
        elif conteggi is not None:
            st.info("Il registro è ancora vuoto.")

    col_giorno, col_ora = st.columns(2)

    with col_giorno:
        st.subheader("Assenza giornaliera")
        assenti = st.multiselect("Seleziona i docenti assenti:", options=elenco_docenti)
        if st.button("Calcola Sostituzioni Giornaliere"):
            if assenti:
                esegui_e_mostra(sh, orario, cattedre, giorno,
                                [(d, ore_giorno) for d in assenti], assenti_giorno=assenti)
            else:
                st.warning("Non hai selezionato nessun docente.")

    with col_ora:
        st.subheader("Assenza oraria")
        docente = st.selectbox("Seleziona il docente assente:", options=elenco_docenti)
        ore_assenza = st.pills("Ore di assenza", ore_giorno, selection_mode="multi")
        if st.button("Calcola Sostituzioni Orarie"):
            if ore_assenza:
                ore_sel = sorted(ore_assenza)
                esegui_e_mostra(sh, orario, cattedre, giorno, [(docente, ore_sel)],
                                assenti_ore={o: [docente] for o in ore_sel})
            else:
                st.warning("Non hai selezionato nessuna ora.")


if __name__ == "__main__":
    main()
