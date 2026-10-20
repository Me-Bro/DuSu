"""Word lists and tables the Grammar Coach rule checks read (pure data + tiny inflection helpers; no I/O).

Everything here is keyed by token KEYS (lowercase, apostrophes kept - see text.py). The tables are deliberately conservative: an entry is
added only when the pattern is wrong in (almost) every context, and each table row carries its own example sentences so the unit tests are
generated from the data (wrong -> hit with the right fix, right -> silent).
"""

from __future__ import annotations

from typing import NamedTuple


def _set(s: str) -> frozenset:
    return frozenset(s.split())


# --------------------------------------------------------------------------------------------------------------------- inflection

_VOW = "aeiou"
_S_IRR = {"be": "is", "have": "has", "do": "does", "go": "goes"}
_DOUBLE = _set("begin forget prefer admit permit refer occur control regret commit submit omit equip compel expel rebel propel transfer upset "
               "remit patrol")
_ING_IRR = {"be": "being", "lie": "lying", "die": "dying", "tie": "tying", "see": "seeing", "agree": "agreeing", "flee": "fleeing",
            "dye": "dyeing", "age": "aging", "singe": "singeing", "free": "freeing", "queue": "queuing", "bake": "baking"}


def _vgroups(w: str) -> int:
    n, prev = 0, False
    for ch in w:
        v = ch in _VOW
        if v and not prev:
            n += 1
        prev = v
    return n


def _cvc(w: str) -> bool:
    return len(w) >= 3 and w[-1] not in _VOW + "wxy" and w[-2] in _VOW and w[-3] not in _VOW


def _doubles(w: str) -> bool:
    return w in _DOUBLE or (_cvc(w) and _vgroups(w) == 1 and not w.endswith("qu"))


def third_s(v: str) -> str:
    """Third-person-singular present: go -> goes, try -> tries, watch -> watches, have -> has."""
    if v in _S_IRR:
        return _S_IRR[v]
    if v.endswith(("s", "x", "z", "ch", "sh")):
        return v + "es"
    if v.endswith("y") and len(v) > 1 and v[-2] not in _VOW:
        return v[:-1] + "ies"
    return v + "s"


def ing_forms(v: str) -> frozenset:
    """Every plausible -ing spelling (canonical first via ing_form)."""
    out = {ing_form(v)}
    if _cvc(v) and not v.endswith("e"):
        out.add(v + v[-1] + "ing")
        out.add(v + "ing")
    return frozenset(out)


def ing_form(v: str) -> str:
    if v in _ING_IRR:
        return _ING_IRR[v]
    if v.endswith("ie"):
        return v[:-2] + "ying"
    if v.endswith(("ee", "ye", "oe")):
        return v + "ing"
    if v.endswith("e"):
        return v[:-1] + "ing"
    if _doubles(v):
        return v + v[-1] + "ing"
    return v + "ing"


def past_forms(v: str) -> frozenset:
    """Regular -ed spellings of a verb (both a doubled and an undoubled variant where it is unclear)."""
    if v.endswith("e"):
        return frozenset({v + "d"})
    if v.endswith("y") and len(v) > 1 and v[-2] not in _VOW:
        return frozenset({v[:-1] + "ied"})
    out = {v + "ed"}
    if _cvc(v):
        out.add(v + v[-1] + "ed")
    return frozenset(out)


def past_regular(v: str) -> str:
    if v.endswith("e"):
        return v + "d"
    if v.endswith("y") and len(v) > 1 and v[-2] not in _VOW:
        return v[:-1] + "ied"
    if _doubles(v):
        return v + v[-1] + "ed"
    return v + "ed"


_PLURAL_IRR = {"child": "children", "man": "men", "woman": "women", "person": "people", "foot": "feet", "tooth": "teeth", "wife": "wives",
               "life": "lives", "knife": "knives", "leaf": "leaves", "half": "halves", "mouse": "mice", "goose": "geese"}


def pluralize(w: str) -> str:
    if w in _PLURAL_IRR:
        return _PLURAL_IRR[w]
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    if w.endswith("y") and len(w) > 1 and w[-2] not in _VOW:
        return w[:-1] + "ies"
    return w + "s"


# --------------------------------------------------------------------------------------------------------------------- verbs

# base v2 v3
_IRREG_TXT = """
arise arose arisen | be was been | bear bore borne | beat beat beaten | become became become | begin began begun | bend bent bent | bet bet bet
bind bound bound | bite bit bitten | bleed bled bled | blow blew blown | break broke broken | breed bred bred | bring brought brought
build built built | burst burst burst | buy bought bought | cast cast cast | catch caught caught | choose chose chosen | cling clung clung
come came come | cost cost cost | creep crept crept | cut cut cut | deal dealt dealt | dig dug dug | do did done | draw drew drawn
drink drank drunk | drive drove driven | eat ate eaten | fall fell fallen | feed fed fed | feel felt felt | fight fought fought
find found found | flee fled fled | fly flew flown | forbid forbade forbidden | forget forgot forgotten | forgive forgave forgiven
freeze froze frozen | get got got | give gave given | go went gone | grow grew grown | hang hung hung | have had had | hear heard heard
hide hid hidden | hit hit hit | hold held held | hurt hurt hurt | keep kept kept | know knew known | lay laid laid | lead led led
leave left left | lend lent lent | let let let | lie lay lain | light lit lit | lose lost lost | make made made | mean meant meant
meet met met | pay paid paid | put put put | quit quit quit | read read read | ride rode ridden | ring rang rung | rise rose risen
run ran run | say said said | see saw seen | seek sought sought | sell sold sold | send sent sent | set set set | shake shook shaken
shine shone shone | shoot shot shot | show showed shown | shut shut shut | sing sang sung | sink sank sunk | sit sat sat | sleep slept slept
slide slid slid | speak spoke spoken | spend spent spent | spin spun spun | spit spat spat | split split split | spread spread spread
stand stood stood | steal stole stolen | stick stuck stuck | strike struck struck | swear swore sworn | sweep swept swept | swim swam swum
swing swung swung | take took taken | teach taught taught | tear tore torn | tell told told | think thought thought | throw threw thrown
understand understood understood | wake woke woken | wear wore worn | win won won | wind wound wound | withdraw withdrew withdrawn
write wrote written
"""
IRREG: dict[str, tuple[str, str]] = {}
for _chunk in _IRREG_TXT.replace("\n", " | ").split("|"):
    _p = _chunk.split()
    if len(_p) == 3:
        IRREG[_p[0]] = (_p[1], _p[2])
EXTRA_V3 = {"get": "gotten", "prove": "proven", "learn": "learnt", "burn": "burnt"}
IRREG["prove"] = ("proved", "proven")

_VERBS_TXT = """
accept act add admit adopt advise afford agree allow announce answer appear apply argue arrive ask attack attend avoid bake bark bathe
become begin believe belong bite blow borrow bother bounce break bring build burn buy call care carry catch change charge chase check
cheer choose claim clean clear climb close collect come compare complain complete concern connect consider continue cook copy cost count
cover crash create cross cry cut damage dance deal decide deliver demand depend describe design destroy develop die disagree discuss divide
do doubt drag draw dream dress drink drive drop earn eat enjoy enter escape exercise exist expect explain express face fail fall fear feed
feel fight fill find finish fit fix fly follow forget forgive gain get give go grow guess handle hang happen hate have hear help hide hit
hold hope hurry hurt imagine improve include inform introduce invite join jump keep kick kill kiss know last laugh lead learn leave lend let
lie like listen live look lose love make manage marry matter mean measure meet mention mind miss mix move need notice obey offer open order
own pack paint pass pay perform pick plan plant play point practice prefer prepare press pretend prevent print promise protect prove pull
push put reach read realize receive recognize record reduce refuse relax remain remember remind repair repeat reply report represent
require rest return ride ring rise rob run sail save say search see seem sell send serve set share shine shoot shop show shut sing sit
sleep smell smile speak spend stand start stay steal stick stop study succeed suffer suggest supply support suppose surprise survive swim
take talk taste teach tell test thank think throw touch train travel treat trust try turn type understand use visit wait wake walk want
warn wash watch wear wish win wonder work worry write
"""
_VERBS_TXT2 = """
affect cause determine define rain snow cancel celebrate chat compete contain contact cough defend delay disappear discover dislike download dry edit elect employ
encourage end entertain examine expand extend fetch fold fry gather greet hire hunt identify ignore impress increase influence insist intend
interest interview judge knock lift lock melt nod obtain occur operate organize pour pray pronounce publish punish raise refer reflect
register regret relate release rely remove rent replace request rescue reserve respect respond retire reveal review reward roll rub scare
scratch select settle shout sigh smoke solve sort spell spoil stare stir stretch struggle suit tend tie tire translate unite vote wander
waste wave weigh welcome whisper wipe wrap appreciate arrange attach attract bless boil book breathe brush calm cheat command communicate
comfort confuse congratulate convince cure deserve disturb divorce donate drown dump emphasize empty engage ensure equal exchange excite
explode fasten fool force glance glow graduate guide hug inspire interrupt invent invest iron lack lean load mail name neglect nurse
object observe pause polish possess praise predict qualify question react realise regard resemble resign resist satisfy scream separate
shave shock slap slow smash sneeze snore spill squeeze starve steer subscribe suspect swallow switch tackle tempt threaten tickle tolerate
tour trace trap trick twist update upload vanish volunteer wink worship yell zoom
"""
BASE_VERBS: frozenset = frozenset(_VERBS_TXT.split()) | frozenset(_VERBS_TXT2.split())
# `be` and the modals are not content verbs: they are handled by their own checks.

V2_FORMS: frozenset = frozenset(v2 for v2, _ in IRREG.values())
V3_FORMS: frozenset = frozenset([v3 for _, v3 in IRREG.values()] + list(EXTRA_V3.values()))
V2_TO_BASE: dict[str, str] = {}
V3_TO_BASE: dict[str, str] = {}
for _b, (_v2, _v3) in IRREG.items():
    if _b == "be":
        continue
    V2_TO_BASE.setdefault(_v2, _b)
    V3_TO_BASE.setdefault(_v3, _b)
for _b, _x in EXTRA_V3.items():
    V3_TO_BASE.setdefault(_x, _b)
# verbs whose V2 is spelled like the base: "she read" is not a missing -s
V2_EQ_BASE: frozenset = frozenset(b for b, (v2, _) in IRREG.items() if v2 == b)
# irregular V2/V3 spellings that are ALSO a base verb or a common noun/adjective: never treated as a wrong tense by themselves
AMBIG_PAST: frozenset = _set("lay wound ground bound rose fell felt bit rung spoke stuck lit shone led")

S_TO_BASE: dict[str, str] = {}
ING_TO_BASE: dict[str, str] = {}
ED_TO_BASE: dict[str, str] = {}
for _b in BASE_VERBS:
    S_TO_BASE.setdefault(third_s(_b), _b)
    for _f in ing_forms(_b):
        ING_TO_BASE.setdefault(_f, _b)
    if _b not in IRREG:
        for _f in past_forms(_b):
            ED_TO_BASE.setdefault(_f, _b)
for _w in list(S_TO_BASE):          # a s-form that is itself a base verb ("press", "miss", "pass") is a base form
    if _w in BASE_VERBS:
        del S_TO_BASE[_w]


def v2_of(base: str) -> str:
    return IRREG[base][0] if base in IRREG else past_regular(base)


def v3_of(base: str) -> str:
    return IRREG[base][1] if base in IRREG else past_regular(base)


def verb_forms(base: str) -> frozenset:
    """Every inflection of a verb, including irregular ones."""
    out = {base, third_s(base)} | set(ing_forms(base))
    if base in IRREG:
        out |= {IRREG[base][0], IRREG[base][1]}
        if base in EXTRA_V3:
            out.add(EXTRA_V3[base])
    else:
        out |= set(past_forms(base))
    return frozenset(out)


def base_of(tok: str) -> str:
    """Best base form of an inflected verb token ('' when it is not a known verb form)."""
    if tok in BASE_VERBS:
        return tok
    return S_TO_BASE.get(tok) or ING_TO_BASE.get(tok) or V2_TO_BASE.get(tok) or V3_TO_BASE.get(tok) or ED_TO_BASE.get(tok) or ""


# words that are both a base verb and a very common noun / adjective: never treat them as a verb on thin evidence
NOUNISH_VERBS = _set("work play rest walk call change visit start trip test dance drive cost point look face set pass present record "
                     "report answer order figure promise plan ride care watch use mind need fit last matter light")

# --------------------------------------------------------------------------------------------------------------------- closed classes

MODALS = _set("can could will would shall should may might must")
PRON_SUBJ = _set("i you he she it we they")
PRON_OBJ = _set("me you him her it us them")
OBJ_OF = {"i": "me", "you": "you", "he": "him", "she": "her", "it": "it", "we": "us", "they": "them"}
DETS = _set("the a an my your his her our their this that these those every each some any no")
FILL = _set("so and but then well okay ok um uh hmm actually basically also now yes no yeah oh see hey hi hello sir please listen look")
WH = _set("what where when why how which")
BE_GET = _set("is am are was were be been being get gets got getting gotten i'm he's she's it's we're you're they're that's who's what's")
CONJ_BREAK = _set("and but so because then when that which if while although though or")
ADV_MID = _set("always never usually often sometimes really also just still only even already generally normally rarely seldom actually "
               "certainly probably definitely simply quickly")
NUM_WORDS = _set("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
                 "nineteen twenty thirty forty fifty sixty hundred thousand a an few couple several many some half")
UNITS_TIME = _set("second seconds minute minutes hour hours day days week weeks month months year years decade decades yr yrs")
UNITS_AFTER_NUM = _set("hours hrs rupees rs rupee dollars dollar usd inr people students persons meters metres km kg words calories per "
                       "minutes seconds percent points marks")
WEEKDAYS = _set("monday tuesday wednesday thursday friday saturday sunday")
MONTHS = _set("january february march april may june july august september october november december")
MONTHS_SAFE = MONTHS - _set("may march august")          # tokens that are also ordinary English words
ORDINAL_WORDS = _set("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth "
                     "sixteenth seventeenth eighteenth nineteenth twentieth thirtieth")
DAYPARTS = _set("morning evening afternoon")
# a noun after "in morning" that makes it a compound modifier ("in morning assembly") - not a missing "the"
DAYPART_MODS = _set("assembly prayer prayers shift shifts session sessions walk show news paper traffic sickness rush routine class classes "
                    "exercise workout coffee tea mass light batch")

# --------------------------------------------------------------------------------------------------------------------- people

# kin and person nouns, with a gender: m / f / e (either).  Used by D15.
KIN: dict[str, str] = {}
for _w in "brother father dad daddy papa uncle son husband nephew grandfather grandpa boyfriend sir".split():
    KIN[_w] = "m"
for _w in "sister mother mom mum mummy mama aunt aunty auntie daughter wife niece grandmother grandma girlfriend madam".split():
    KIN[_w] = "f"
for _w in ("friend teacher doctor boss cousin neighbour neighbor colleague manager principal classmate roommate partner "
           "professor mentor trainer coach tutor student").split():
    KIN[_w] = "e"
KIN_PLURAL: frozenset = frozenset(pluralize(w) for w in KIN) | _set("parents relatives")
MALE_NOUNS = _set("man boy gentleman father brother uncle son husband king guy sir")
FEMALE_NOUNS = _set("woman girl lady mother sister aunt daughter wife queen madam")
POSS = _set("my our his her their your")
KIN_ADJ = _set("elder younger older little best close good big small eldest youngest only dear old new favourite favorite great true real "
               "own other first second")

PROFESSIONS = _set("""
engineer doctor teacher student lawyer nurse driver designer developer programmer manager accountant architect writer singer dancer
farmer businessman banker electrician plumber cook chef tailor carpenter mechanic pilot officer clerk salesman shopkeeper artist
musician actor actress journalist reporter photographer scientist researcher analyst consultant intern trainee fresher graduate
housewife homemaker tutor lecturer professor technician receptionist waiter barber painter soldier constable pharmacist dentist
surgeon freelancer entrepreneur trader secretary assistant supervisor engineer
""")
# modifiers that may stand between "I am" and the role ("I am software engineer" -> "a software engineer")
ROLE_MODS = _set("""
software hardware civil mechanical electrical electronics computer chemical data web mobile full stack backend frontend junior senior lead
assistant associate young good great bad new famous professional private government medical engineering law hardworking honest simple
poor rich small big first second final third fresh part time
""")
ROLE_NEXT_OK = _set("""
in at of and but by for from with working who which that so because since as now too also here there today currently nowadays only on near
after before to then or i my he she we they you
""")
ROLE_NOT_NEXT = _set("council union body life id")
GENERIC_PERSON = _set("boy girl man woman person human")

# --------------------------------------------------------------------------------------------------------------------- nouns

UNCOUNTABLE = _set("""
water money traffic food rice milk tea coffee bread advice information news furniture luggage baggage homework work weather music
knowledge equipment electricity sugar salt oil air noise health happiness patience pollution rain snow cash jewelry jewellery
research progress feedback evidence housework machinery staff vocabulary software scenery
""")
# {wrong plural: right}
PLURAL_ERRORS: dict[str, str] = {
    "informations": "information", "advices": "advice", "furnitures": "furniture", "luggages": "luggage", "baggages": "baggage",
    "knowledges": "knowledge", "equipments": "equipment", "homeworks": "homework", "staffs": "staff", "peoples": "people",
    "childrens": "children", "mens": "men", "womens": "women", "feets": "feet", "newses": "news", "researches": "research",
    "feedbacks": "feedback",
}
# error plurals that STT also writes for the possessive ("womens rights"): only flag when a function word / the end follows
PLURAL_ERR_POSSESSIVE = _set("peoples childrens mens womens staffs")
POSS_FOLLOW_OK = _set("""
are is were was and or but in at to of for from with who that because also too go went play played have has had like love need want can will
do does did came come said say think know live lived work worked
""")
UNCOUNT_A = _set("information advice furniture luggage knowledge equipment homework news baggage")
UNCOUNT_A_ADJ = _set("good bad nice great useful valuable helpful important new big huge wonderful excellent best better sound free "
                     "detailed general practical personal constructive brief quick simple small")
COUNT_PLURALS = _set("""
people friends students things books cars problems questions hours days years times children mistakes members girls boys kids persons
places cities countries movies songs games jobs reasons ideas words subjects teachers brothers sisters
""")
COMPARATIVES = _set("""
better best worse worst bigger biggest smaller smallest taller tallest shorter shortest longer longest faster fastest easier easiest
harder hardest higher highest lower lowest older oldest younger youngest newer newest cheaper cheapest cleaner cleanest smarter smartest
brighter brightest happier happiest healthier healthiest stronger strongest wiser wisest nicer nicest richer richest poorer poorest
louder loudest safer safest simpler simplest wider widest deeper deepest heavier heaviest lighter lightest earlier earliest nearer
nearest closer closest quicker quickest slower slowest greater greatest finer finest fresher warmer colder hotter dirtier prettier
""")

# singular countable nouns (with an easy plural) for "one of my friend", "every students"
SING_COUNT = _set("""
friend student teacher brother sister book thing reason problem person place movie song game job member girl boy kid child colleague
cousin subject question idea word country city company family story habit hobby language
""")
PLURAL_OF: dict[str, str] = {w: pluralize(w) for w in SING_COUNT}
SING_OF: dict[str, str] = {v: k for k, v in PLURAL_OF.items()}
SING_OF.update({"others": "other", "days": "day", "years": "year", "weeks": "week", "months": "month", "minutes": "minute",
                "hours": "hour", "times": "time", "mistakes": "mistake", "classes": "class", "lessons": "lesson", "tasks": "task",
                "subjects": "subject", "things": "thing", "people": "person"})
SING_OF.pop("people", None)

# --------------------------------------------------------------------------------------------------------------------- T1: prepositions


class PrepRow(NamedTuple):
    rule: str
    head: str                       # "v:discuss" = every inflection of the verb, "x:angry" = that exact token
    wrong: tuple                    # tokens right after the head that are wrong (empty = an insertion row)
    fix: tuple                      # what they become (for an insertion row: what is inserted before the next token)
    ex_wrong: str
    ex_fixed: str
    ex_right: str
    need_next: frozenset = frozenset()    # the first token after the match must be one of these (after one determiner if skipdet)
    not_next: frozenset = frozenset()
    need_prev: frozenset = frozenset()
    not_prev: frozenset = frozenset()
    not_next2: frozenset = frozenset()    # the token two after the match must not be one of these
    skipdet: bool = False


def _p(rule, head, wrong, fix, ex_wrong, ex_fixed, ex_right, need_next="", not_next="", need_prev="", not_prev="", not_next2="", skipdet=False):
    return PrepRow(rule, head, tuple(wrong.split()), tuple(fix.split()), ex_wrong, ex_fixed, ex_right, _set(need_next), _set(not_next),
                   _set(need_prev), _set(not_prev), _set(not_next2), skipdet)


_PRON_OBJ = "me him her them us you"
_SUBJECTS_AT = "english maths math mathematics science studies speaking writing sports cooking singing dancing drawing painting coding hindi " \
               "physics chemistry biology history grammar communication programming football cricket music art"
_SAFE_PURPOSE = ("buy get see meet take bring collect learn visit watch pay check find ask eat drink play submit give pick fetch call help "
                 "finish complete attend join tell discuss talk speak enjoy relax clean make have apply register renew recharge deposit withdraw do")

PREP_TABLE: tuple[PrepRow, ...] = (
    # ---- extra preposition: delete it -----------------------------------------------------------------------------------------
    _p("pr.extra_prep", "v:discuss", "about", "", "we discussed about the plan yesterday", "we discussed the plan yesterday",
       "we discussed the plan yesterday"),
    _p("pr.extra_prep", "v:reach", "to", "", "she reached to the office early", "she reached the office early", "she reached the office early",
       need_next="the my his her our their your this that home office school college hotel station airport delhi mumbai pune chennai "
                 "kolkata india there here me him them us you"),
    _p("pr.extra_prep", "v:enter", "into", "", "he entered into the room quietly", "he entered the room quietly", "he entered the room quietly",
       need_next="the my his her our their your this that room house hall building school class shop office market"),
    _p("pr.extra_prep", "v:attend", "to", "", "i attended to the meeting yesterday", "i attended the meeting yesterday",
       "i attended the meeting yesterday",
       need_next="meeting meetings class classes wedding party function session lecture training interview event seminar workshop school "
                 "college course", skipdet=True),
    _p("pr.extra_prep", "v:marry", "with", "", "i married with him in 2015", "i married him in 2015", "i married him in 2015",
       not_prev="is am are was were be been being get gets got getting gotten i'm he's she's it's we're you're they're"),
    _p("pr.extra_prep", "v:ask", "to", "", "he asked to me about it", "he asked me about it", "he asked me about it", need_next=_PRON_OBJ),
    _p("pr.extra_prep", "v:tell", "to", "", "she told to me a secret", "she told me a secret", "she told me a secret", need_next=_PRON_OBJ),
    _p("pr.extra_prep", "v:contact", "to", "", "please contact to me tomorrow", "please contact me tomorrow", "please contact me tomorrow",
       need_next=_PRON_OBJ),
    _p("pr.extra_prep", "v:explain", "about", "", "can you explain about the topic", "can you explain the topic", "can you explain the topic"),
    _p("pr.extra_prep", "v:describe", "about", "", "please describe about your family", "please describe your family",
       "please describe your family"),
    _p("pr.extra_prep", "v:mention", "about", "", "he mentioned about the problem", "he mentioned the problem", "he mentioned the problem"),
    _p("pr.extra_prep", "v:emphasize", "on", "", "the teacher emphasized on practice", "the teacher emphasized practice",
       "the teacher emphasized practice"),
    _p("pr.extra_prep", "v:emphasise", "on", "", "the teacher emphasised on practice", "the teacher emphasised practice",
       "the teacher emphasised practice"),
    _p("pr.extra_prep", "v:reach", "at", "", "we reached at home late", "we reached home late", "we reached home late",
       need_next="home the my his her our their your office school college hotel airport station"),
    _p("pr.extra_prep", "v:go", "to", "", "i went to home early", "i went home early", "i went home early", need_next="home",
       not_next2="page screen town tuition"),
    _p("pr.extra_prep", "v:come", "to", "", "he came to home late", "he came home late", "he came home late", need_next="home",
       not_next2="page screen town tuition"),
    _p("pr.extra_prep", "v:return", "to", "", "she returned to home yesterday", "she returned home yesterday", "she returned home yesterday",
       need_next="home", not_next2="page screen town tuition"),
    _p("pr.extra_prep", "v:go", "to", "", "he went to abroad for work", "he went abroad for work", "he went abroad for work", need_next="abroad"),
    _p("pr.extra_prep", "v:cope", "up", "", "i cannot cope up with this", "i cannot cope with this", "i cannot cope with this", need_next="with"),
    # ---- wrong preposition: replace it ----------------------------------------------------------------------------------------
    _p("pr.wrong_prep", "x:married", "with", "to", "she is married with my cousin", "she is married to my cousin",
       "she is married to my cousin",
       need_prev="is am are was were be been being get gets got getting gotten i'm he's she's it's we're you're they're",
       not_next="kids children child two three four five six one a an no"),
    _p("pr.wrong_prep", "x:angry", "on", "with", "he is angry on me", "he is angry with me", "he is angry with me"),
    _p("pr.wrong_prep", "x:afraid", "from", "of", "i am afraid from dogs", "i am afraid of dogs", "i am afraid of dogs"),
    _p("pr.wrong_prep", "x:scared", "from", "of", "she is scared from water", "she is scared of water", "she is scared of water"),
    _p("pr.wrong_prep", "x:good", "in", "at", "i am good in english", "i am good at english", "i am good at english", need_next=_SUBJECTS_AT),
    _p("pr.wrong_prep", "x:bad", "in", "at", "he is bad in maths", "he is bad at maths", "he is bad at maths", need_next=_SUBJECTS_AT),
    _p("pr.wrong_prep", "x:interested", "on", "in", "i am interested on music", "i am interested in music", "i am interested in music"),
    _p("pr.wrong_prep", "x:interested", "for", "in", "she is interested for this job", "she is interested in this job",
       "she is interested in this job"),
    _p("pr.wrong_prep", "x:proud", "on", "of", "i am proud on you", "i am proud of you", "i am proud of you"),
    _p("pr.wrong_prep", "x:jealous", "on", "of", "he is jealous on his friend", "he is jealous of his friend", "he is jealous of his friend"),
    _p("pr.wrong_prep", "x:different", "with", "from", "this is different with that", "this is different from that",
       "this is different from that"),
    _p("pr.wrong_prep", "v:depend", "of", "on", "it depends of the weather", "it depends on the weather", "it depends on the weather"),
    _p("pr.wrong_prep", "v:consist", "from", "of", "the team consists from five people", "the team consists of five people",
       "the team consists of five people"),
    _p("pr.wrong_prep", "v:complain", "on", "about", "he complained on his boss", "he complained about his boss",
       "he complained about his boss"),
    _p("pr.wrong_prep", "x:attention", "on", "to", "please pay attention on the class", "please pay attention to the class",
       "please pay attention to the class", need_prev="pay pays paid paying"),
    _p("pr.wrong_prep", "x:congratulations", "for", "on", "congratulations for your success", "congratulations on your success",
       "congratulations on your success"),
    _p("pr.wrong_prep", "v:participate", "on", "in", "i participated on the competition", "i participated in the competition",
       "i participated in the competition",
       need_next="competition contest event events discussion debate activity activities quiz match game games sports workshop seminar class",
       skipdet=True),
    _p("pr.wrong_prep", "v:belong", "from", "to", "i belong from a small village", "i belong to a small village", "i belong to a small village"),
    _p("pr.wrong_prep", "v:arrive", "to", "at", "we arrived to the station late", "we arrived at the station late", "we arrived at the station late",
       need_next="station airport hotel office school college hospital party meeting venue gate house", skipdet=True),
    _p("pr.wrong_prep", "v:arrive", "to", "in", "we arrived to delhi late", "we arrived in delhi late", "we arrived in delhi late",
       not_next="find see discover meet welcome hear take begin start be do get"),
    # ---- missing preposition: insert it ---------------------------------------------------------------------------------------
    _p("pr.missing_to", "v:listen", "", "to", "i listen music every day", "i listen to music every day", "i listen to music every day",
       need_next="music songs song radio news podcast podcasts the my his her their our your this that me him them us you"),
    _p("pr.missing_to", "v:explain", "", "to", "explain me the rule", "explain to me the rule", "explain it to me", need_next="me him them us"),
    _p("pr.missing_to", "v:reply", "", "to", "please reply me soon", "please reply to me soon", "please reply to me soon",
       need_next="me him them us you"),
    _p("pr.missing_to", "v:talk", "", "to", "i talked him yesterday", "i talked to him yesterday", "i talked to him yesterday",
       need_next="me him them us you", not_next2="into out through"),
    _p("pr.missing_to", "v:wait", "", "for", "please wait me here", "please wait for me here", "please wait for me here",
       need_next="me him them us you", not_next2="out"),
    _p("pr.missing_to", "v:look", "", "at", "look him carefully", "look at him carefully", "look at him carefully",
       need_next="me him them us", not_next2="in up over out after through around down into"),
    # ---- "for" + verb of purpose -----------------------------------------------------------------------------------------------
    _p("pr.for_purpose", "v:go", "for", "to", "i went for buy milk", "i went to buy milk", "i went to buy milk", need_next=_SAFE_PURPOSE),
    _p("pr.for_purpose", "v:come", "for", "to", "she came for meet me", "she came to meet me", "she came to meet me", need_next=_SAFE_PURPOSE),
    _p("pr.for_purpose", "x:here", "for", "to", "i am here for meet you", "i am here to meet you", "i am here to meet you",
       need_next=_SAFE_PURPOSE),
    _p("pr.for_purpose", "x:there", "for", "to", "he is there for help us", "he is there to help us", "he is there to help us",
       need_next=_SAFE_PURPOSE),
)

# --------------------------------------------------------------------------------------------------------------------- T2: patterns
# A PatRow is a short token pattern: every element is a literal token, a frozenset of tokens or a named predicate (see detectors._PRED).
# `rng` = (a, b): the matched tokens [a, b) are replaced by `fix`; fix items: a literal str, an int k (copy matched token k),
# or a tuple (op, k, arg) - op in map | s3 | be | plural | singular | ing | base | obj.


class PatRow(NamedTuple):
    rule: str
    elems: tuple
    rng: tuple
    fix: tuple
    ex_wrong: str
    ex_fixed: str
    ex_right: str
    not_next: frozenset = frozenset()
    not_prev: frozenset = frozenset()
    need_prev: frozenset = frozenset()
    unit_start: bool = False
    note: str = ""


def _q(rule, elems, rng, fix, ex_wrong, ex_fixed, ex_right, not_next="", not_prev="", need_prev="", unit_start=False, note=""):
    return PatRow(rule, tuple(frozenset(e.split()) if isinstance(e, str) and " " in e else e for e in elems), rng, tuple(fix),
                  ex_wrong, ex_fixed, ex_right, _set(not_next), _set(not_prev), _set(need_prev), unit_start, note)


_PLURAL_QUANT = "many several few two three four five six seven eight nine ten"
_SAY_MAP = {"say": "tell", "said": "told", "says": "tells", "saying": "telling"}
_TELL_MAP = {"tell": "say", "told": "said", "tells": "says", "telling": "saying"}
_OPEN_MAP = {"open": ("turn", "on"), "opened": ("turned", "on"), "opens": ("turns", "on"), "opening": ("turning", "on")}
_CLOSE_MAP = {"close": ("turn", "off"), "closed": ("turned", "off"), "closes": ("turns", "off"), "closing": ("turning", "off")}
APPLIANCES = "light lights fan fans tv television ac geyser heater lamp radio cooler"
_ADJ_BE = ("beautiful good nice happy smart tall intelligent kind hardworking busy tired hot cold big small important difficult easy "
           "interesting careful clever lazy polite rich poor strong weak famous helpful honest friendly funny lovely sweet young old")
_STATIVE = "agree disagree know want need love hate think believe understand forget prefer remember"
_ING_VERBS = "enjoy enjoyed enjoys enjoying avoid avoided avoids avoiding finish finished finishes finishing mind practice practiced practices " \
             "practicing quit consider considered considers considering imagine imagined imagines imagining"
_PERSON_NOUNS = "person man woman people boy girl friend friends teacher teachers doctor doctors guy guys lady ladies someone anyone everyone " \
                "colleague colleagues student students children men women"
_SUBJ_ANY = "i we they you he she"
_SUBJ_NOI = "we they you he she"

# (wrong verb lemma, right verb lemma, nouns that need a determiner, nouns fine without one, determiners allowed in between)
COLLOCATIONS = (
    ("do", "make", "mistake plan decision promise call effort excuse suggestion", "mistakes noise decisions promises calls efforts excuses suggestions"),
    ("make", "do", "", "homework exercise exercises shopping housework laundry"),
    ("say", "tell", "lie joke story truth secret", "lies jokes stories secrets"),
    ("make", "take", "photo photograph selfie bath shower nap walk", "photos selfies"),
    ("make", "have", "party", "parties"),
)
COLLO_DETS = _set("a an the some any my your his her our their")


def _form_map(a: str, b: str) -> dict:
    fa = (a, third_s(a), v2_of(a), v3_of(a), ing_form(a))
    fb = (b, third_s(b), v2_of(b), v3_of(b), ing_form(b))
    m: dict = {}
    for x, y in zip(fa, fb):
        m.setdefault(x, y)
    return m


def _collo_rows() -> list:
    rows = []
    ex = {
        ("do", "mistake"): ("i did a mistake in the test", "i made a mistake in the test", "i made a mistake in the test"),
        ("do", "plan"): ("we did a plan for the trip", "we made a plan for the trip", "we made a plan for the trip"),
        ("do", "decision"): ("they did a decision quickly", "they made a decision quickly", "they made a decision quickly"),
        ("do", "promise"): ("he did a promise to me", "he made a promise to me", "he made a promise to me"),
        ("do", "call"): ("i did a call to my mother", "i made a call to my mother", "i made a call to my mother"),
        ("do", "effort"): ("she did an effort to learn", "she made an effort to learn", "she made an effort to learn"),
        ("do", "excuse"): ("he did an excuse for being late", "he made an excuse for being late", "he made an excuse for being late"),
        ("do", "suggestion"): ("i did a suggestion in the meeting", "i made a suggestion in the meeting", "i made a suggestion in the meeting"),
        ("do", "mistakes"): ("i do mistakes when i speak fast", "i make mistakes when i speak fast", "i make mistakes when i speak fast"),
        ("do", "noise"): ("the kids did noise all night", "the kids made noise all night", "the kids made noise all night"),
        ("do", "decisions"): ("he does decisions very slowly", "he makes decisions very slowly", "he makes decisions very slowly"),
        ("do", "promises"): ("he does promises he cannot keep", "he makes promises he cannot keep", "he makes promises he cannot keep"),
        ("do", "calls"): ("she did calls to every client", "she made calls to every client", "she made calls to every client"),
        ("do", "efforts"): ("they did efforts to win", "they made efforts to win", "they made efforts to win"),
        ("do", "excuses"): ("he does excuses every day", "he makes excuses every day", "he makes excuses every day"),
        ("do", "suggestions"): ("she did suggestions to the team", "she made suggestions to the team", "she made suggestions to the team"),
        ("make", "homework"): ("i made homework after dinner", "i did homework after dinner", "i did homework after dinner"),
        ("make", "exercise"): ("i make exercise every morning", "i do exercise every morning", "i do exercise every morning"),
        ("make", "exercises"): ("we made exercises in class", "we did exercises in class", "we did exercises in class"),
        ("make", "shopping"): ("she makes shopping on sunday", "she does shopping on sunday", "she does shopping on sunday"),
        ("make", "housework"): ("he makes housework daily", "he does housework daily", "he does housework daily"),
        ("make", "laundry"): ("she makes laundry on friday", "she does laundry on friday", "she does laundry on friday"),
        ("say", "lie"): ("he said a lie to me", "he told a lie to me", "he told a lie to me"),
        ("say", "joke"): ("she said a joke in class", "she told a joke in class", "she told a joke in class"),
        ("say", "story"): ("grandma said a story every night", "grandma told a story every night", "grandma told a story every night"),
        ("say", "truth"): ("please say the truth", "please tell the truth", "please tell the truth"),
        ("say", "secret"): ("i said a secret to him", "i told a secret to him", "i told a secret to him"),
        ("say", "lies"): ("he says lies all the time", "he tells lies all the time", "he tells lies all the time"),
        ("say", "jokes"): ("she says jokes to everyone", "she tells jokes to everyone", "she tells jokes to everyone"),
        ("say", "stories"): ("he says stories to the kids", "he tells stories to the kids", "he tells stories to the kids"),
        ("say", "secrets"): ("i do not say secrets to anyone", "i do not tell secrets to anyone", "i do not tell secrets to anyone"),
        ("make", "photo"): ("i made a photo of the temple", "i took a photo of the temple", "i took a photo of the temple"),
        ("make", "photograph"): ("he made a photograph of us", "he took a photograph of us", "he took a photograph of us"),
        ("make", "selfie"): ("we made a selfie at the beach", "we took a selfie at the beach", "we took a selfie at the beach"),
        ("make", "bath"): ("i make a bath every morning", "i take a bath every morning", "i take a bath every morning"),
        ("make", "shower"): ("he made a shower after the match", "he took a shower after the match", "he took a shower after the match"),
        ("make", "nap"): ("i made a nap after lunch", "i took a nap after lunch", "i took a nap after lunch"),
        ("make", "walk"): ("we make a walk in the evening", "we take a walk in the evening", "we take a walk in the evening"),
        ("make", "photos"): ("i made photos of the temple", "i took photos of the temple", "i took photos of the temple"),
        ("make", "selfies"): ("we made selfies at the beach", "we took selfies at the beach", "we took selfies at the beach"),
        ("make", "party"): ("we made a party on sunday", "we had a party on sunday", "we had a party on sunday"),
        ("make", "parties"): ("they make parties every month", "they have parties every month", "they have parties every month"),
    }
    for a, b, need_det, bare in COLLOCATIONS:
        fm = _form_map(a, b)
        for n in need_det.split():
            w, f, r = ex[(a, n)]
            rows.append(PatRow("wd.collocation", (frozenset(fm), COLLO_DETS, n), (0, 1), (("map", 0, fm),), w, f, r,
                               frozenset(), frozenset(), frozenset(), False, f"{a}->{b} {n}"))
        for n in bare.split():
            w, f, r = ex[(a, n)]
            rows.append(PatRow("wd.collocation", (frozenset(fm), n), (0, 1), (("map", 0, fm),), w, f, r,
                               frozenset(), frozenset(), frozenset(), False, f"{a}->{b} {n}"))
    return rows


PATTERN_TABLE: tuple[PatRow, ...] = tuple([
    # ---- ag.there_is_plural -------------------------------------------------------------------------------------------------
    _q("ag.there_is_plural", ("there", "is was", ("pred", "pl_quant")), (1, 2), (("map", 1, {"is": "are", "was": "were"}),),
       "there is many people in the hall", "there are many people in the hall", "there are many people in the hall",
       not_next="a minutes seconds hours days weeks months years rupees dollars km kilometres meters minutes"),
    # ---- ag.quantifier_number -----------------------------------------------------------------------------------------------
    _q("ag.quantifier_number", ("one each", "of", "my your his her our their the", ("pred", "sing_count")), (3, 4), (("plural", 3, None),),
       "one of my friend is a doctor", "one of my friends is a doctor", "one of my friends is a doctor"),
    _q("ag.quantifier_number", ("every each", ("pred", "plural_noun")), (1, 2), (("singular", 1, None),),
       "every students must come", "every student must come", "every student must come", not_prev="of"),
    _q("ag.quantifier_number", (_PLURAL_QUANT, ("pred", "sing_count")), (1, 2), (("plural", 1, None),),
       "many student came late", "many students came late", "many students came late",
       not_next="card id council union loan visa life discount rate fee fees pass", not_prev="a the this that every each one"),
    _q("ag.quantifier_number", ("buy bought get got need needs want wants bring brought sell sold", "some", "vegetable"), (2, 3),
       (("plural", 2, None),), "i bought some vegetable from the market", "i bought some vegetables from the market",
       "i bought some vegetables from the market", not_next="soup curry oil dish salad stock garden market"),
    # ---- wd.say_tell --------------------------------------------------------------------------------------------------------
    _q("wd.say_tell", ("say said says saying", "me him us them"), (0, 1), (("map", 0, _SAY_MAP),),
       "he said me to come", "he told me to come", "he told me to come", not_next="self selves"),
    _q("wd.say_tell", ("tell told tells telling", "that", "i we they he she it you there"), (0, 1), (("map", 0, _TELL_MAP),),
       "he told that he was late", "he said that he was late", "he said that he was late"),
    # ---- st.be_misuse -------------------------------------------------------------------------------------------------------
    _q("st.be_misuse", ("am", _STATIVE), (0, 1), (), "i am agree with you", "i agree with you", "i agree with you"),
    _q("st.be_misuse", ("are", _STATIVE), (0, 1), (), "we are agree with that", "we agree with that", "we agree with that"),
    _q("st.be_misuse", ("is", _STATIVE), (0, 2), (("s3", 1, None),), "she is want a new phone", "she wants a new phone", "she wants a new phone"),
    _q("st.be_misuse", ("am", "not", _STATIVE), (0, 3), ("don't", 2), "i am not agree with this", "i don't agree with this",
       "i don't agree with this"),
    _q("st.be_misuse", ("are", "not", _STATIVE), (0, 3), ("don't", 2), "they are not agree with us", "they don't agree with us",
       "they don't agree with us"),
    _q("st.be_misuse", ("is", "not", _STATIVE), (0, 3), ("doesn't", 2), "he is not agree with me", "he doesn't agree with me",
       "he doesn't agree with me"),
    _q("st.be_misuse", ("i'm", _STATIVE), (0, 2), ("i", 1), "i'm agree with you", "i agree with you", "i agree with you"),
    _q("st.be_misuse", (_SUBJ_NOI, "very", ("pred", "adj_be")), (1, 2), (("be", 0, None), 1),
       "she very smart and everyone knows it", "she is very smart and everyone knows it", "she is very smart and everyone knows it",
       not_prev="is am are was were be been not"),
    # ---- st.adverb_position -------------------------------------------------------------------------------------------------
    _q("st.adverb_position", (_SUBJ_ANY, "yesterday", ("pred", "v2")), (0, 3), ("yesterday", 0, 2),
       "i yesterday went to the market", "yesterday i went to the market", "yesterday i went to the market"),
    _q("st.adverb_position", (_SUBJ_ANY, "always never usually often sometimes generally normally", "is am are"), (1, 3), (2, 1),
       "he always is late", "he is always late", "he is always late"),
    _q("st.adverb_position", ("i we they you", "very", "like love enjoy miss hate", "it him her them this that you"), (1, 4),
       (2, 3, "very", "much"), "i very like it", "i like it very much", "i like it very much"),
    _q("st.adverb_position", ("he she", "very", "like love enjoy miss hate", "it him her them this that you"), (1, 4),
       (("s3", 2, None), 3, "very", "much"), "she very love him", "she loves him very much", "she loves him very much"),
    _q("st.adverb_position", ("he she", "very", "likes loves enjoys misses hates", "it him her them this that you"), (1, 4),
       (2, 3, "very", "much"), "he very likes it", "he likes it very much", "he likes it very much"),
    # ---- st.verb_pattern ----------------------------------------------------------------------------------------------------
    _q("st.verb_pattern", ("want wants wanted need needs needed", "that", "you he she they we i", ("pred", "base_or_s")), (1, 4),
       (("obj", 2, None), "to", ("base", 3, None)), "i want that you come tomorrow", "i want you to come tomorrow",
       "i want you to come tomorrow"),
    _q("st.verb_pattern", (_ING_VERBS, "to", ("pred", "plain_verb")), (1, 3), (("ing", 2, None),),
       "i enjoy to sing", "i enjoy singing", "i enjoy singing", not_prev="used"),
    _q("st.verb_pattern", ("i", "am", "used", "to", ("pred", "plain_verb")), (4, 5), (("ing", 4, None),),
       "i am used to wake up early", "i am used to waking up early", "i am used to waking up early"),
    _q("st.verb_pattern", ("i'm", "used", "to", ("pred", "plain_verb")), (3, 4), (("ing", 3, None),),
       "i'm used to wake up early", "i'm used to waking up early", "i'm used to waking up early"),
    _q("st.verb_pattern", ("look looks looked looking", "forward", "to", ("pred", "plain_verb")), (3, 4), (("ing", 3, None),),
       "i look forward to meet you", "i look forward to meeting you", "i look forward to meeting you"),
    _q("st.verb_pattern", ("make makes made making let lets", "me him her them us you", "to", ("pred", "plain_verb")), (2, 3), (),
       "she made him to cry", "she made him cry", "she made him cry"),
    # ---- pn.myself_intro ----------------------------------------------------------------------------------------------------
    _q("pn.myself_intro", ("myself", ("pred", "not_myself_next")), (0, 1), ("i", "am"), "myself rahul from delhi", "i am rahul from delhi",
       "i am rahul from delhi", unit_start=True),
    _q("pn.myself_intro", ("my", "self", ("pred", "not_myself_next")), (0, 2), ("i", "am"), "my self rahul from delhi", "i am rahul from delhi",
       "i am rahul from delhi", unit_start=True),
    # ---- pn.relative --------------------------------------------------------------------------------------------------------
    _q("pn.relative", (_PERSON_NOUNS, "which"), (1, 2), ("who",), "the person which called me was rude", "the person who called me was rude",
       "the person who called me was rude", not_next="one ones of"),
] + _collo_rows())
# appliance rows (multi-token fixes) are appended here because their maps hold tuples
PATTERN_TABLE = PATTERN_TABLE + (
    _q("wd.collocation", (frozenset(_OPEN_MAP), "the", frozenset(APPLIANCES.split())), (0, 1), (("map", 0, _OPEN_MAP),),
       "please open the light", "please turn on the light", "please turn on the light", not_next="cabinet stand unit"),
    _q("wd.collocation", (frozenset(_CLOSE_MAP), "the", frozenset(APPLIANCES.split())), (0, 1), (("map", 0, _CLOSE_MAP),),
       "please close the fan", "please turn off the fan", "please turn off the fan", not_next="cabinet stand unit"),
    _q("wd.collocation", ("off", "the", frozenset(APPLIANCES.split())), (0, 1), ("turn", "off"), "please off the light", "please turn off the light",
       "please turn off the light", need_prev="please you can could will would just then and quickly go"),
    _q("wd.collocation", ("on", "the", frozenset(APPLIANCES.split())), (0, 1), ("turn", "on"), "please on the fan", "please turn on the fan",
       "please turn on the fan", need_prev="please you can could will would just then and quickly go"),
)

# --------------------------------------------------------------------------------------------------------------------- T3: Indianisms


class IndRow(NamedTuple):
    slug: str
    phrase: tuple
    fix: tuple
    ex_wrong: str
    ex_fixed: str
    ex_right: str
    need_next: frozenset = frozenset()
    not_next: frozenset = frozenset()


def _i(phrase, fix, ex_wrong, ex_fixed, ex_right, need_next="", not_next=""):
    return IndRow(phrase.replace(" ", "_"), tuple(phrase.split()), tuple(fix.split()), ex_wrong, ex_fixed, ex_right,
                  _set(need_next), _set(not_next))


INDIAN_TABLE: tuple[IndRow, ...] = (
    _i("do the needful", "take care of it", "please do the needful as soon as possible", "please take care of it as soon as possible",
       "please take care of it as soon as possible"),
    _i("do needful", "take care of it", "kindly do needful today", "kindly take care of it today", "kindly take care of it today"),
    _i("prepone", "bring forward", "can we prepone the meeting", "can we bring forward the meeting", "can we bring forward the meeting"),
    _i("preponed", "brought forward", "they preponed the exam", "they brought forward the exam", "they brought forward the exam"),
    _i("revert back", "reply", "i will revert back to you", "i will reply to you", "i will reply to you"),
    _i("reverted back", "replied", "she reverted back quickly", "she replied quickly", "she replied quickly"),
    _i("reply back", "reply", "please reply back soon", "please reply soon", "please reply soon"),
    _i("passed out", "graduated", "i passed out from college in 2019", "i graduated from college in 2019", "he passed out because of the heat",
       need_next="from of"),
    _i("cousin brother", "cousin", "he is my cousin brother", "he is my cousin", "he is my cousin"),
    _i("cousin sister", "cousin", "she is my cousin sister", "she is my cousin", "she is my cousin"),
    _i("your good name", "your name", "may i know your good name", "may i know your name", "may i know your name"),
    _i("my good name", "my name", "my good name is rahul", "my name is rahul", "my name is rahul"),
    _i("out of station", "out of town", "i am out of station this week", "i am out of town this week", "i am out of town this week"),
    _i("outstation", "out of town", "we have an outstation trip", "we have an out of town trip", "we have an out of town trip"),
    _i("return back", "return", "i will return back tomorrow", "i will return tomorrow", "i will return tomorrow"),
    _i("returned back", "returned", "she returned back yesterday", "she returned yesterday", "she returned yesterday"),
    _i("returning back", "returning", "we are returning back soon", "we are returning soon", "we are returning soon"),
    _i("returns back", "returns", "he returns back at night", "he returns at night", "he returns at night"),
    _i("i have a doubt", "i have a question", "i have a doubt in this sum", "i have a question in this sum", "i have a question in this sum",
       not_next="about whether if that"),
    _i("i have one doubt", "i have a question", "i have one doubt in this topic", "i have a question in this topic",
       "i have a question in this topic", not_next="about whether if that"),
    _i("i have doubt", "i have a question", "i have doubt in this topic", "i have a question in this topic", "i have a question in this topic",
       not_next="about whether if that"),
    _i("too good", "really good", "the food was too good", "the food was really good", "it is too good to be true", not_next="to for"),
    _i("too nice", "really nice", "the hotel was too nice", "the hotel was really nice", "it is too nice to waste", not_next="to for"),
    _i("today itself", "today", "i will finish it today itself", "i will finish it today", "i will finish it today"),
    _i("now itself", "right now", "do it now itself", "do it right now", "do it right now"),
    _i("tomorrow itself", "tomorrow", "we will start tomorrow itself", "we will start tomorrow", "we will start tomorrow"),
    _i("here itself", "right here", "keep it here itself", "keep it right here", "keep it right here"),
    _i("there itself", "right there", "wait there itself", "wait right there", "wait right there"),
    _i("updation", "update", "the updation of records is slow", "the update of records is slow", "the update of records is slow"),
    _i("native place", "hometown", "my native place is pune", "my hometown is pune", "my hometown is pune"),
    _i("according to me", "in my opinion", "according to me this is wrong", "in my opinion this is wrong", "in my opinion this is wrong"),
    _i("take tension", "stress", "do not take tension about it", "do not stress about it", "do not stress about it"),
    _i("taking tension", "stressing", "stop taking tension about it", "stop stressing about it", "stop stressing about it"),
    _i("did my graduation", "graduated", "i did my graduation in 2018", "i graduated in 2018", "i graduated in 2018"),
    _i("from where are you", "where are you from", "from where are you", "where are you from", "where are you from"),
    _i("kindly revert", "please reply", "kindly revert by tomorrow", "please reply by tomorrow", "please reply by tomorrow"),
    _i("gave exam", "took an exam", "i gave exam yesterday", "i took an exam yesterday", "i took an exam yesterday"),
    _i("give exam", "take an exam", "i will give exam tomorrow", "i will take an exam tomorrow", "i will take an exam tomorrow"),
)
# {phrase: replacement} view (the rule id is `ind.lexicon#<phrase with underscores>`)
INDIAN_LEX: dict[str, str] = {" ".join(r.phrase): " ".join(r.fix) for r in INDIAN_TABLE}

# --------------------------------------------------------------------------------------------------------------------- misc tables

# a/an: spelling vs sound
A_SOUND_CONSONANT = ("eu", "ew", "one", "once", "ubiq", "ufo", "uk", "ukr", "unif", "unit", "unic", "unio", "uniq", "univ", "unil", "unis",
                     "unip", "unix", "use", "usu", "uti", "uten", "uter", "uri", "uran", "usa", "uae", "ussr")
AN_SOUND_VOWEL = ("hour", "honest", "honor", "honour", "heir")
AN_EITHER = ("histor", "hotel", "herb", "heroic", "hypothe")
A_FUNC_NEXT = _set("and or is are was were as at am an a in on of if it its it's up us i i'm you")
SPOKEN_LETTER_AN = "fhlmnrsx"
