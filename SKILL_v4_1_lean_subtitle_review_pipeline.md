# SKILL.md — Telugu-to-English Subtitle Review Pipeline v4.1 Lean

## Purpose

Generate a clean human review workbook from a Telugu SBV/SRT file.

This skill is intended for many spiritual/scriptural discourse episodes across different topics. It should not be tuned to one episode.

## Final Output

The automation pass should produce only:
1. Master Review Workbook (.xlsx)
2. Optional raw JSON/debug file

Do not generate the final English SRT in this pass. Final SRT generation should happen only after human review.

The workbook must contain exactly these columns:
- Cue Number
- Timecode
- Telugu Cue
- AI Generated English Cue
- Human Review Correction

## Source of Truth

The Telugu subtitle file is authoritative.

Do not add:
- external commentary
- internet knowledge
- prior chapter knowledge not present in the discourse
- invented explanations
- polished summaries not grounded in Telugu

Use context only to understand the cue, not to move meaning away from its timestamp.

## Translation Standard

The English cue should be:
- faithful to the Telugu meaning
- plain and natural
- review-ready for subtitle authors
- aligned to the Telugu cue
- complete without skipped or blank cues

If the Telugu is simple, the English should remain simple.

## Whole-Discourse Understanding

Before translating cue chunks, read the full Telugu episode and build a concise internal discourse brief.

The brief should include only what helps translation:
- main teaching flow
- questions, doubts, prayers, or reflections
- examples and analogies
- Sanskrit terms or quotations
- speaker perspective / voice notes
- opening and closing/sign-off cues
- likely cue-boundary risks

Keep the brief concise. Do not create a long essay.

## Cue Preservation

Every Telugu cue must receive an English output in the automated translation pass.

Do not:
- leave English blank
- skip cues
- absorb one Telugu cue entirely into another cue
- change cue order
- change timestamps
- overwrite Telugu source text

If a cue is a short fragment or continuation, provide the best natural English fragment or continuation for that cue.

## Tone and Fidelity

Preserve Swamiji’s explanatory teaching tone.

Use plain spoken English, not:
- dramatic retelling
- literary prose
- sermon-style rewriting
- emotionally stronger wording unless clearly present in Telugu

Do not introduce quoted inner speech or explicit thought quotation unless the Telugu clearly presents direct speech or direct quoted thought.

Where Telugu indicates thought, intention, or feeling without direct quotation, prefer natural narrative English.

## Perspective and Voice

Preserve speaker perspective and inner-voice fidelity.

If Telugu presents a person’s own doubt, prayer, question, or inner reflection directly, preserve that perspective in English.

Do not convert direct inner questioning into detached third-person narration unless Telugu clearly does so.

## Natural English

Faithfulness does not mean carrying Telugu sentence structure mechanically into English.

If a literal rendering sounds stiff, repetitive, or unnatural in English, convert it into natural spoken English while preserving meaning.

Do not repeat the same causal idea twice in English unless Telugu clearly repeats it for emphasis.

## Sanskrit and Transliteration

Colon-based long-vowel transliteration is mandatory for Sanskrit names, technical terms, salutations, and quoted verses wherever they appear.

Use known required forms such as:
- Sri:manna:ra:yana
- Bhagavad Gi:tha
- Sri Ra:ma
- Krushna
- A:thma
- Parama:thma
- Jna:na
- Bhakthi
- Karma
- Yajna
- Vive:ka
- Sa:nkhyam
- Yo:ga
- Avatha:ra
- Pra:rabdha
- A:ga:mi

Do not use simplified spellings such as Bhagavad Gita, Sri Rama, Atma, Jnana, Bhakti, Yoga, or Srimannarayana when the required transliterated form is known.

Apply this rule to all Sanskrit words in the discourse, not only recurring examples.

Italicize Sanskrit technical terms, names used as sacred/technical terms, quotations, and verses using Markdown-style asterisks where appropriate.

Example:
- *Karma*
- *Yajna*
- *A:thma*
- *Jai Sri:manna:ra:yana*

## Scriptural Quotations

If Swamiji quotes a Sanskrit verse or phrase, preserve it.

Translate only explanations explicitly given by Swamiji.

If Swamiji merely quotes a verse and moves on, do not add a meaning.

## Questions and Rhetorical Style

Preserve questions as questions.

Do not convert questions into narrative summaries unless Telugu clearly does so.

## Success Criteria

A successful automation pass produces a workbook where:
- every Telugu cue appears exactly once
- every cue has an AI-generated English cue
- timestamps are preserved
- Telugu source text is preserved
- closing/sign-off cues are preserved
- Sanskrit transliteration mostly follows the required style
- human reviewers mainly polish or correct a small number of cues
