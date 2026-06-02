You are simulating a realistic spoken-word podcast transcript — a HOST
interviewing a GUEST.

Topic / premise: {topic}
Tone: {tone}
Target audience: {audience}
Approximate length: {length}

Write the transcript as a back-and-forth interview between two speakers. Rules:

- Use clear speaker labels at the start of each turn: "HOST:" and "GUEST:" (or
  invent specific first names — Sarah, Marcus, etc. — if you prefer. Keep
  labels consistent throughout.)
- The GUEST is the subject-matter expert who lived the story. They do roughly
  70-75% of the talking. The HOST asks substantive questions, occasionally
  clarifies or pushes back, and steers the conversation through the beats.
- The HOST asks 3-5 questions total across the transcript, each one opening
  up a new beat of the story (setup, turning point, what they did, results,
  takeaway / generalizable rule).
- The GUEST's answers must include:
  - The messy cadence of real spoken language: false starts ("so the thing
    is..."), filler words ("like", "you know", "right?", "I want to say"),
    occasional self-corrections, sentences that change direction.
  - At least one specific story or example with concrete details.
  - At least three concrete numbers or data points (figures that sound real).
  - At least one quotable line or counterintuitive premise that downstream
    modules can latch onto as a hook.
- NO markdown formatting. NO headers. NO bullet points. NO bold. Just
  spoken-text turns separated by blank lines, each prefixed with its speaker
  label.
- Open with the HOST briefly introducing the topic and guest. Close with a
  brief HOST wrap-up ("Where can people find your work?", "Thanks for the
  time", etc.) and a one-line GUEST sign-off.
- Length: 600-900 words total across both speakers.

Return ONLY the transcript text. No preamble. No "Sure, here's the transcript:".
No closing commentary. Just the transcript itself.
