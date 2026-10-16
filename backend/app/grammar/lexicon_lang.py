"""Word lists for the language gates, the segmenter and the flow metrics (pure data, no behaviour).

HINGLISH_STOP   ~120 UNAMBIGUOUS Roman-Hindi words. A word that is also English (to, par, main, hi, ho, kar, bas, do, me, the, sun, log, fir ...)
                is deliberately NOT here: this list decides "this sentence is not English", so a false hit costs the learner a skipped sentence.
ENGLISH_STOP    common English function words (apostrophe forms included, as text.tokenize keeps the apostrophe).
LOANWORDS       Indian words and names that are never flaggable: an English sentence containing "chai" or "Rahul" is still English, and a rule
                check or a model mark touching one of these is dropped.
DISCOURSE_*     tokens that open / close a spoken sentence without being part of its content (not counted as core words).
CONNECTORS      sentence connectors grouped by category, for the flow metrics.
"""

from __future__ import annotations

HINGLISH_STOP = frozenset("""
hai hain hoon tha thi thae nahi nahin kya kyun kyu kyunki kyuki kaise kaisa kaisi kahan kab kaun kitna kitni
mera meri mere tera teri tere tumhara tumhari tumhare hamara hamari hamare apna apni apne
tum tumhe tumko aap aapko aapka aapki aapke humko hume humein unka unki unke unko usko isko inhe unhe mujhe mujhko mujh
yeh woh wo
kal aaj abhi bahut bohot bhaut bhi toh lekin magar aur isliye agar jab tab phir matlab theek thik accha acha achha haan
chahiye chahta chahti karna karta karti karte karo kiya kiye karke gaya gayi gaye raha rahi rahe hota hoti hote hoga hogi honge
sakta sakti sakte bolo bola boli bolna dekho dekh dekhna suno sunna
ghar paisa paise kaam sab sabko kuch kuchh koi kisi kisko bilkul zaroor jaldi wahan yahan yaha idhar udhar kaha kehna kehta kehti
batao bataya samajh samjha samjhi pata jaisa jaise waise aise itna itni utna thoda thodi zyada jyada
ladka ladki beta beti bachcha khana peena uthna padhna likhna seekhna sochna chalo chalna chaliye milna jaana aana
sahi galat mushkil aasan wala wali wale sirf tak saath sath liye baat waqt raat subah shaam naam
ka ki ke ko ne se mein
""".split())

ENGLISH_STOP = frozenset("""
the a an and or but if so because of to in on at for with from by about as into like than then that this these those
it its is are was were be been being am do does did done have has had having will would can could shall should may might must
not no yes i me my mine we us our ours you your yours he him his she her hers they them their theirs
what which who whom whose when where why how there here all any some each every both few more most other such only own same too very just
also still even again once up down out off over under between through during before after above below while until against now
don't doesn't didn't can't won't isn't aren't wasn't weren't haven't hasn't hadn't shouldn't couldn't wouldn't
i'm i've i'll i'd you're you've you'll you'd he's she's it's that's there's we're we've we'll they're they've they'll let's what's who's
""".split())

# Indian words / names / places that are never flaggable (lowercase; matched on token keys).
LOANWORDS = frozenset("""
chai dhaba lakh lakhs crore crores ji didi diwali deepavali holi eid tiffin auto rickshaw samosa paneer roti dal sabzi biryani masala lassi dosa idli
vada paratha naan chapati ghee gulab jamun jalebi ladoo puri kebab tandoori thali paan bindi saree sari kurta dupatta lehenga dhoti salwar chappal
mehendi mehndi rangoli puja pooja aarti mandir guru yoga karma mantra namaste namaskar ashram swami pandit sadhu bhai bhaiya behen bhabhi chacha
chachi amma appa nani nana dada dadi mausi bua saheb sahab babu yaar dost arre arey jugaad dharna panchayat sarkar zamindar paisa paise rupee rupees
rupaye mela bazaar bazar mandi kirana chowk gali mohalla basti chaiwala wallah tehsil taluka lathi ghat ganga yamuna himalaya ayurveda
bollywood tollywood kollywood desi gulab lathi kulfi pakora chaat bhel golgappa pani sev namkeen thanda tadka chutney raita pulao khichdi
kheer halwa rasgulla barfi peda modak poha upma uttapam sambar rasam chole bhature rajma kadhi tikka korma vindaloo lassi
raj rahul rohit amit ankit sanjay vijay ajay anil sunil suresh ramesh mahesh ganesh rajesh deepak vikas vivek arjun krishna sita radha priya pooja
neha sneha anita sunita kavita savita rekha geeta seema meena ritu shweta divya anjali nisha komal shivam aman rohan sachin virat dhoni kohli
sharma verma gupta singh kumar yadav patel reddy iyer nair mehta joshi mishra pandey tiwari chauhan thakur khan ali ahmed
delhi mumbai bombay kolkata calcutta chennai madras bangalore bengaluru hyderabad pune jaipur lucknow patna ranchi bhopal indore nagpur surat
ahmedabad chandigarh kanpur varanasi banaras agra kerala punjab gujarat bihar rajasthan haryana assam odisha goa kashmir tamil telugu hindi urdu
marathi bengali gujarati punjabi kannada malayalam bhojpuri
iit iim cbse upsc ias ips neet jee ielts tcs infosys wipro isro
""".split())

# a sentence opens with these without saying anything yet (up to 3 are not counted as core words); phrases are matched as token pairs
DISCOURSE_LEAD = frozenset(("um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mm", "so", "okay", "ok", "well", "like", "actually",
                            "basically", "and", "but", "then", "yeah"))
DISCOURSE_LEAD_PHRASES = frozenset((("you", "know"), ("i", "mean")))
DISCOURSE_TRAIL = frozenset(("right", "okay", "ok"))
DISCOURSE_TRAIL_PHRASES = frozenset((("you", "know"),))

# connectors by category (phrases are space-separated token keys); used by flow.py
CONNECTORS = {
    "add": ("also", "moreover", "furthermore", "besides", "additionally", "plus", "in addition", "as well as"),
    "contrast": ("but", "however", "although", "though", "whereas", "yet", "on the other hand", "even though", "instead", "while"),
    "cause": ("because", "since", "so", "therefore", "thus", "hence", "as a result", "due to", "that is why"),
    "example": ("for example", "for instance", "such as", "especially", "namely", "like that"),
    "sequence": ("first", "firstly", "second", "secondly", "third", "then", "next", "finally", "after", "before", "later", "afterwards",
                 "meanwhile", "after that", "at last", "lastly", "in the end", "at first"),
    "condition": ("if", "unless", "otherwise", "as long as", "in case", "provided"),
}
# words that are connectors only when they OPEN the sentence (they are ordinary words elsewhere: "the first time", "a week after")
CONNECTORS_START_ONLY = frozenset(("first", "second", "third", "next", "after", "before", "since", "while", "yet", "plus", "later", "instead",
                                   "so", "like that", "at first", "after that"))

# segment.py: words that may START a new sentence when an unpunctuated chunk is too long
CUT_CONNECTORS = frozenset(("so", "then", "however", "anyway", "also", "first", "finally", "next", "later", "now"))
CUT_CONNECTORS_PRON = frozenset(("but", "and", "then"))
SUBJECT_PRONOUNS = frozenset(("i", "we", "he", "she", "they", "it", "you", "there", "this", "that", "my", "our", "his", "her", "their"))

# segment.py: a "." after these is an abbreviation, not the end of a sentence (lowercase, no dots)
ABBREVIATIONS = frozenset(("mr", "mrs", "ms", "dr", "prof", "vs", "etc", "st", "jr", "sr", "rs", "no", "inc", "ltd", "co", "mt", "approx", "dept",
                           "govt", "vol", "fig", "misc", "appt", "ave", "gen", "col", "capt", "lt", "sgt", "rev", "hon", "pvt"))
ABBREV_NEEDS_DIGIT = frozenset(("no", "fig", "vol", "approx"))     # "No. 5" is an abbreviation, "I said no. Then" is not

# gating.py
NUMBER_WORDS = frozenset(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "double", "triple", "oh",
                          "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                          "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand"))
HALLU_TOKENS = frozenset(("thank", "you", "thanks", "bye", "okay", "ok", "so", "um", "uh", "yeah", "yes", "no", "the", "end", "subscribe",
                          "watching", "for"))
YESNO = frozenset(("yes", "no", "okay", "ok", "yeah", "yep", "nope", "sure", "right", "fine", "alright"))
