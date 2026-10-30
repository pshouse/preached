# EVAL-PLAINQ: plain-language eval questions written blind to the corpus

Branch `feat/eval-plainq` from `origin/feat/eval-deleak` (`7b0fea9`). Date: 2026-10-30.

## Corpus was not consulted before the first commit

The 30 questions were written and committed before any read of the Wesley corpus, the search index, sermon titles, the expected answers in `eval/questions.jsonl`, or any report that lists titles.

That commit is `4c53c663dbebd5202e36183966c59357dd5eb2df` (`Add 30 blind plain-language eval questions`). It is the first commit on `feat/eval-plainq`. Its only change is `eval/plain_candidates.jsonl`. The question file was not edited after that commit.

## What was saved

`eval/plain_candidates.jsonl`: 30 lines, ids `p-001` through `p-030`. Fields are `id`, `question`, `group` (`plain-blind`), and `answerable_guess` (`yes` / `no` / `unsure`). There are no expected answers, no sermon ids, and no quotes.

Guesses, made without looking at the sermons: 23 `yes`, 2 `unsure`, 5 `no`. The five `no` rows are modern topics an eighteenth-century preacher is unlikely to have addressed, kept as unanswerable candidates. The two `unsure` rows are old worries sitting on a modern object (a phone; anxiety medicine).

## The 30 questions

| id | guess | question |
| --- | --- | --- |
| p-001 | yes | I don't know how to pray anymore. It just feels like I'm talking to the ceiling and nothing comes back. |
| p-002 | yes | my mom died last month and i cant stop crying at work. does the sad part ever get smaller |
| p-003 | yes | We are so broke. I feel guilty buying the kids anything that isn't on sale. What are we supposed to do with money when there isn't enough? |
| p-004 | yes | sorry this is a mess. my wife says shes done trying and i dont even know what im asking i just dont want my family to fall apart |
| p-005 | yes | I'm not even sure God is real anymore. I go on Sundays because my family does, but I feel like I'm faking it. |
| p-006 | yes | theres something i did a long time ago that i never told anyone. i say ive moved on but i still feel dirty about it |
| p-007 | yes | I yelled at my kids again tonight and I saw the look on my daughter's face. I don't want to be this angry. |
| p-008 | yes | i told everyone i quit drinking and then i bought a bottle on the way home. i dont know why i keep doing this |
| p-009 | yes | I can be in a full room at church and still feel completely alone. I don't have one person I could call. |
| p-010 | yes | work has taken over my whole life and im still behind. is it bad that i daydream about quitting and disappearing for a while |
| p-011 | yes | They found something on the scan and I have to wait two weeks to know how bad it is. I can't sleep. What do I even say to God? |
| p-012 | yes | my son is 15 and he wont talk to me. if i ask about school he shuts the door. i feel like im losing him |
| p-013 | yes | Someone at church told people something about me that isn't true, and now half the room is weird with me. They still smile. Do I have to just let it go? |
| p-014 | yes | im scared of dying. like actually scared, not just wondering. i think about it when i try to fall asleep |
| p-015 | yes | God feels far. I used to feel something when I prayed and now it's just quiet, and I don't know if I did something wrong. |
| p-016 | yes | help i messed up bad |
| p-017 | yes | why wont he answer |
| p-018 | yes | Can God forgive me if I don't feel sorry the way people say I should? I mostly just feel numb. |
| p-019 | yes | i get jealous of my friends and their vacations and then i hate that this is who i am |
| p-020 | yes | My dad was mean when I was little. Now I have a baby and I'm scared I'm going to turn into him. |
| p-021 | yes | ive been praying for my sister for months and she just keeps getting worse. im starting to feel stupid for asking |
| p-022 | yes | Our church is splitting into sides and people are talking about each other. I love these people but I don't want to pick a team. |
| p-023 | yes | i work sunday mornings so we can pay rent. i miss church and i feel guilty and i also cant quit the shift |
| p-024 | unsure | i keep looking at stuff on my phone late at night that i shouldnt. i delete the apps and then i put them right back. i feel gross |
| p-025 | unsure | My doctor put me on medicine for anxiety and a lady at church said that means I'm not trusting God. I still take the pill. Am I wrong? |
| p-026 | no | cant stop scrolling tiktok at like 2am and then i feel like everyone else has a better life. is that just me being weak |
| p-027 | no | I met a guy on a dating app and we might get serious. Is that a bad way to find someone to marry, or is it fine? |
| p-028 | no | im scared about the climate and that my kids wont get a normal future. i lie awake thinking about fires and floods. what do i do with that |
| p-029 | no | My company is replacing people with AI and I might not have a job next year. How do I stop panicking? |
| p-030 | no | is it ok if church is just me watching the livestream in bed. i havent actually gone in months and i kinda dont want to |
