"""Grammar Lab - the tense-form classifier (pure). Run: python tests/lab/unit_forms.py  (from the repo root; no database, no network)."""
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, "tests/lab")
from _h import check, section, main
from app.lab import forms as F

PS, PC, PP, PPC = "present_simple", "present_continuous", "present_perfect", "present_perfect_continuous"
AS, AC, AP, APC = "past_simple", "past_continuous", "past_perfect", "past_perfect_continuous"
FS, FC, FP, FPC = "future_simple", "future_continuous", "future_perfect", "future_perfect_continuous"

# sentence -> the set of forms it must read as (exactly)
GOLD = [
    # ---- present simple
    ("Ram drinks tea every morning.", {PS}), ("They play cricket on Sundays.", {PS}), ("She does not like coffee.", {PS}), ("He doesn't work here.", {PS}),
    ("Do you speak English?", {PS}), ("Does she live in Delhi?", {PS}), ("The sun rises in the east.", {PS}), ("I am a student.", {PS}), ("My father is a doctor.", {PS}),
    ("We are not late.", {PS}), ("I have a red pen.", {PS}), ("She has two brothers.", {PS}), ("Water boils at 100 degrees.", {PS}), ("Where do you live?", {PS}),
    ("He goes to school by bus.", {PS}), ("My mother cooks very well.", {PS}), ("What does your brother do?", {PS}), ("Does he have a car?", {PS}),
    # ---- present continuous
    ("He is playing football now.", {PC}), ("I am reading a book.", {PC}), ("They are not watching TV.", {PC}), ("Is she cooking dinner?", {PC}), ("What are you doing?", {PC}),
    ("We are waiting for the bus.", {PC}), ("The children are sleeping.", {PC}), ("I'm studying for my exam.", {PC}), ("She's talking to her friend.", {PC}), ("Are they coming today?", {PC}),
    ("It is raining heavily.", {PC}), ("He isn't listening to me.", {PC}), ("My sister is learning to drive these days.", {PC}),
    # ---- present perfect
    ("I have finished my homework.", {PP}), ("She has gone to the market.", {PP}), ("They have not eaten yet.", {PP}), ("Has he arrived?", {PP}), ("Have you seen my phone?", {PP}),
    ("We have lived here for ten years.", {PP}), ("He has already left.", {PP}), ("I've read this book.", {PP}), ("She hasn't called me.", {PP}), ("Have they won the match?", {PP}),
    ("He's gone out.", {PP}), ("I have been to Mumbai twice.", {PP}), ("The train has just come.", {PP}), ("Has the new teacher arrived?", {PP}), ("I have known him since 2015.", {PP}),
    # ---- present perfect continuous
    ("I have been waiting for two hours.", {PPC}), ("She has been studying since morning.", {PPC}), ("They have been playing for an hour.", {PPC}), ("It has been raining all day.", {PPC}),
    ("Have you been working here for long?", {PPC}), ("He hasn't been sleeping well.", {PPC}), ("How long has she been learning English?", {PPC}), ("We've been living here since 2020.", {PPC}),
    # ---- past simple
    ("Ram played cricket yesterday.", {AS}), ("She went to the market.", {AS}), ("They did not come to the party.", {AS}), ("Did you see the movie?", {AS}), ("He didn't call me.", {AS}),
    ("I was at home last night.", {AS}), ("We were very tired.", {AS}), ("My brother bought a new bike.", {AS}), ("Where did you go?", {AS}), ("She wrote a letter to her friend.", {AS}),
    ("I had a bad cold last week.", {AS}), ("He came late.", {AS}), ("The match started at five.", {AS}), ("Was he angry?", {AS}), ("They ate dinner at nine.", {AS}),
    # ---- past continuous
    ("He was playing football.", {AC}), ("I was reading a book at that time.", {AC}), ("They were not watching TV.", {AC}), ("Was she cooking dinner?", {AC}), ("What were you doing?", {AC}),
    ("The children were sleeping.", {AC}), ("We were waiting for the bus.", {AC}), ("It was raining all evening.", {AC}), ("He wasn't listening.", {AC}), ("Were they coming?", {AC}),
    # ---- past perfect
    ("I had finished my homework before he came.", {AP, AS}), ("She had gone to the market.", {AP}), ("They had not eaten.", {AP}), ("Had he arrived?", {AP}), ("Had you seen the film before?", {AP}),
    ("The train had already left.", {AP}), ("He hadn't called me.", {AP}), ("We had lived there for ten years.", {AP}), ("I'd finished my work.", {AP}), ("Had the teacher arrived?", {AP}),
    # ---- past perfect continuous
    ("I had been waiting for two hours.", {APC}), ("She had been studying since morning.", {APC}), ("They had been playing for an hour.", {APC}), ("It had been raining all day.", {APC}),
    ("Had you been working there for long?", {APC}), ("He hadn't been sleeping well.", {APC}), ("How long had she been learning English?", {APC}),
    # ---- future simple
    ("Ram will come tomorrow.", {FS}), ("They will play cricket on Sunday.", {FS}), ("She will not go there.", {FS}), ("He won't help us.", {FS}), ("Will you call me?", {FS}),
    ("I will be happy to help.", {FS}), ("We'll meet at five.", {FS}), ("It will rain tonight.", {FS}), ("Where will you stay?", {FS}), ("I am going to visit my aunt.", {FS}),
    ("She is going to buy a car.", {FS}), ("They are not going to join us.", {FS}), ("I will have a cup of tea.", {FS}), ("Will the train arrive on time?", {FS}),
    # ---- future continuous
    ("I will be waiting for you.", {FC}), ("She will be studying at five.", {FC}), ("They will not be playing tomorrow.", {FC}), ("Will you be coming?", {FC}), ("He'll be sleeping by then.", {FC}),
    ("This time tomorrow I will be flying to Delhi.", {FC}), ("What will you be doing at nine?", {FC}),
    # ---- future perfect
    ("I will have finished by five.", {FP}), ("She will have left by then.", {FP}), ("They will not have arrived.", {FP}), ("Will he have finished?", {FP}), ("We'll have eaten by eight.", {FP}),
    ("By next year I will have lived here for ten years.", {FP}), ("The train will have gone before we reach.", {FP, PS}),
    # ---- future perfect continuous
    ("I will have been working here for five years.", {FPC}), ("She will have been studying for two hours.", {FPC}), ("They will have been playing since morning.", {FPC}),
    ("Will you have been waiting long?", {FPC}), ("By June, he will have been teaching for ten years.", {FPC}),
    # ---- two clauses
    ("I was sleeping when he called.", {AC, AS}), ("If it rains, I will stay at home.", {PS, FS}), ("She said that he was sleeping.", {AS, AC}),
    ("When I reached, the train had left.", {AS, AP}), ("I have lived here since I was a child.", {PP, AS}), ("He will call me when he reaches.", {FS, PS}),
]

section("gold sentences -> forms")
for s, want in GOLD:
    got = set(F.forms_of(s))
    check(f"{s!r} -> {sorted(want)}", got == want, f"got {sorted(got)}")

section("ambiguous irregular verbs return both forms (never a guess)")
check("'I put it on the table.' is present or past", set(F.forms_of("I put it on the table.")) == {PS, AS}, F.forms_of("I put it on the table."))
check("'He cut the cake.' is present or past", set(F.forms_of("He cut the cake.")) == {PS, AS})
check("'He cuts the cake.' is present", set(F.forms_of("He cuts the cake.")) == {PS})
check("'She read the book yesterday.' is present or past (read = read)", set(F.forms_of("She read the book yesterday.")) == {PS, AS})
check("'I have read the book.' is present perfect", set(F.forms_of("I have read the book.")) == {PP})

section("the classifier says nothing when it cannot tell")
for s in ("", "   ", "Good morning", "Tea", "....", "12345"):
    check(f"{s!r} -> no form", F.forms_of(s) == frozenset(), F.forms_of(s))

section("do-support + have: have is the main verb (found by an author's real sentences)")
for sent, want in (("Where did you have lunch yesterday?", {AS}), ("They did not have breakfast.", {AS}), ("Do you have a pen?", {PS}), ("Does she have a car?", {PS}), ("He doesn't have time.", {PS}),
                   ("Did he have dinner?", {AS}), ("Have you had lunch?", {PP}), ("She had had enough.", {AP})):
    check(f"{sent!r} -> {sorted(want)}", set(F.forms_of(sent)) == want, sorted(F.forms_of(sent)))

section("by the time / as soon as split a clause; a fronted subordinate clause does not hide a question")
check("'The train will have left by the time Ram reaches the station' = future perfect + present simple", set(F.forms_of("The train will have left by the time Ram reaches the station.")) == {FP, PS})
check("...and fronted with a comma, the same", set(F.forms_of("By the time Ram reaches the station, the train will have left.")) == {FP, PS})
check("'I will call you as soon as I reach' = future simple + present simple", set(F.forms_of("I will call you as soon as I reach.")) == {FS, PS})
check("question_in sees the question behind a fronted clause", F.question_in("By the time we get there, will Amit have been writing for five hours?"))
check("question_in: a plain statement is not one", not F.question_in("By the time we get there, Amit will have been writing for five hours."))
check("question_in: 'when he was young' alone is not one", not F.question_in("When he was young, he lived in Delhi."))
check("a preposition before the wh-phrase: at what time will", F.is_question(F.norm_tokens("At what time will the guests reach?")))
check("...in which room does she sleep", F.is_question(F.norm_tokens("In which room does she sleep?")))

section("is_question: when / where / why / who need the helping verb right after them")
for sent, want in (("When Rohan's train will reach Delhi", False), ("Where he is going", False), ("When will Rohan's train reach Delhi?", True), ("Where is he going?", True), ("Why did you leave?", True)):
    check(f"is_question({sent!r}) == {want}", F.is_question(F.norm_tokens(sent)) == want, F.norm_tokens(sent))

section("is_question: wh-phrases, and a when-clause is not a question")
for sent, want in (("What time did the train arrive?", True), ("How many books do you have?", True), ("Which book does she like?", True), ("Where is she?", True), ("How long have you been waiting?", True),
                   ("Whose bag is this?", True), ("When he was young, he lived in Delhi.", False), ("When the train was late, we waited.", False), ("What you have is enough.", False),
                   ("Who plays cricket?", False), ("Do you know where he lives?", True), ("I know where he lives.", False)):
    check(f"is_question({sent!r}) == {want}", F.is_question(F.norm_tokens(sent)) == want, F.norm_tokens(sent))

section("learner mistakes still read as what they are")
check("'He is play' reads as present simple (be as main verb) - the checker uses the DIFF for the real message", set(F.forms_of("He is play.")) == {PS})
check("'He play football' reads as present simple", set(F.forms_of("He play football.")) == {PS})
check("'I have went there' reads as present perfect", set(F.forms_of("I have went there.")) == {PP})
check("'She has saw it' reads as present perfect", set(F.forms_of("She has saw it.")) == {PP})
check("'He had went' reads as past perfect", set(F.forms_of("He had went.")) == {AP})
check("'I will going' reads as future simple", set(F.forms_of("I will going.")) == {FS})

section("normalisation")
check("don't -> do not", F.norm_tokens("I don't know") == ["i", "do", "not", "know"], F.norm_tokens("I don't know"))
check("dont (no apostrophe, speech-to-text) -> do not", F.norm_tokens("I dont know") == ["i", "do", "not", "know"])
check("he's gone -> he has gone", F.norm_tokens("He's gone") == ["he", "has", "gone"], F.norm_tokens("He's gone"))
check("he's playing -> he is playing", F.norm_tokens("He's playing") == ["he", "is", "playing"], F.norm_tokens("He's playing"))
check("I'm -> i am", F.norm_tokens("I'm tired") == ["i", "am", "tired"])
check("we'll -> we will", F.norm_tokens("We'll go") == ["we", "will", "go"])
check("going to + verb -> will", F.norm_tokens("She is going to buy a car.") == ["she", "will", "buy", "a", "car"], F.norm_tokens("She is going to buy a car."))
check("going to the market is NOT a future marker", F.norm_tokens("I am going to the market.") == ["i", "am", "going", "to", "the", "market"], F.norm_tokens("I am going to the market."))
check("fillers are dropped", F.norm_tokens("um he plays uh cricket") == ["he", "plays", "cricket"])
check("a ram's (possessive) stays", F.norm_tokens("Ram's book is here") == ["ram's", "book", "is", "here"])
check("bounded", len(F.norm_tokens("word " * 5000)) <= F.MAX_TOKENS)

section("kinds")
for tok, want in (("play", {"base"}), ("plays", {"s"}), ("playing", {"ing"}), ("played", {"v2", "v3"}), ("went", {"v2"}), ("gone", {"v3"}), ("put", {"base", "v2", "v3"}),
                  ("studies", {"s"}), ("studied", {"v2", "v3"}), ("running", {"ing"}), ("wrote", {"v2"}), ("written", {"v3"}), ("morning", set()), ("is", set()), ("does", set())):
    check(f"kinds({tok}) == {sorted(want)}", set(F.kinds(tok)) == want, F.kinds(tok))

section("is_question / has_negation / is_devanagari")
check("question: does he play", F.is_question(["does", "he", "play"]))
check("question: where is she", F.is_question(["where", "is", "she"]))
check("not a question: he plays", not F.is_question(["he", "plays"]))
check("negation: he does not play", F.has_negation(["he", "does", "not", "play"]))
check("devanagari detected", F.is_devanagari("मैं स्कूल जाता हूँ"))
check("latin is not devanagari", not F.is_devanagari("I go to school"))

main("lab forms")
