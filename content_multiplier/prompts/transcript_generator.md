You are simulating a realistic spoken-word podcast transcript — the kind of
output OpenAI Whisper would produce if it transcribed a real human talking
into a microphone for a few minutes.

Topic / premise: {topic}
Tone: {tone}
Target audience: {audience}
Approximate length: {length}

Write the transcript as if a single host is talking. Rules:

- Use the cadence of real spoken language. Include false starts ("so the
  thing is..."), filler words ("like", "you know", "right?", "I want to say"),
  hesitations, sentences that change direction mid-thought, and the occasional
  small self-correction.
- NO markdown formatting. NO headers. NO bullet points. NO bold. NO labels
  like "Host:" — just paragraphs of spoken text separated by blank lines.
- Include at least one specific story or example with concrete details.
- Include at least three concrete numbers or data points (figures that *sound*
  real — this is a test transcript, not journalism).
- Include at least one quotable line or counterintuitive premise that
  downstream modules can use as a hook.
- End with a clear takeaway and a brief wrap-up like "that's what I've got,
  happy to take questions" or similar.
- Length: 600-900 words.

Return ONLY the transcript text. No preamble. No "Sure, here's the transcript:".
No closing commentary. Just the transcript itself.
