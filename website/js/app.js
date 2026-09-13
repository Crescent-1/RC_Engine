/* Website-only demonstration and email-draft enquiry. No generation API or client data. */
(function () {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const letters = ['A', 'B', 'C', 'D'];
  const questions = [
    {
      type: 'Main idea', title: 'What is the central argument of the passage?', correct: 2,
      options: ['More detailed maps can eventually represent every resident’s experience.', 'Community maps should replace official maps because they include more voices.', 'Maps should be judged by their purpose and the consequences of what they omit.', 'The unavoidable partiality of maps makes their accuracy impossible to assess.'],
      rationale: 'The final paragraph proposes a practical standard: make the purpose and limits visible, then ask whether an omission matters to the person using the map.',
      wrong: ['Paragraph 2 challenges the idea that adding detail can produce completeness; some experiences cannot share one symbol.', 'The author values participation but explains that community maps also make choices and can exclude people.', '', 'The accessible-route example explicitly shows how an incomplete map can still be judged against a concrete promise.']
    },
    {
      type: 'Inference', title: 'Which claim about community mapping is best supported?', correct: 0,
      options: ['It can broaden participation while continuing to leave some perspectives unheard.', 'It succeeds only when participants agree on a single account of each place.', 'It cannot improve on official maps unless every resident attends the meetings.', 'It resolves differences of experience by collecting enough survey responses.'],
      rationale: 'Participation changes who can influence the map, but meeting arrangements and category choices may still exclude people. Improvement and continuing limitations can coexist.',
      wrong: ['', 'The passage does not require a single shared account; it notes that different experiences need not cancel each other out.', 'This adds an absolute condition. The author questions who remains unheard without saying that partial participation has no value.', 'Paragraph 2 distinguishes differences of experience from missing survey data. More responses need not erase those differences.']
    },
    {
      type: 'Paragraph function', title: 'What role does the second paragraph play in the argument?', correct: 3,
      options: ['It demonstrates that transport maps deliberately conceal economic inequality.', 'It replaces the need for accurate mapping with an emphasis on personal feelings.', 'It presents community mapping as a complete solution to official omissions.', 'It questions whether accumulating detail is enough to make a map complete.'],
      rationale: 'The paragraph first entertains the appeal of a more complete map, then explains why adding detail cannot resolve every difference of experience.',
      wrong: ['The transport example is in paragraph 1, and the author does not claim deliberate concealment of inequality.', 'The paragraph does not abandon accuracy. It explains a limitation of representing different experiences with a single symbol.', 'Community projects enter in paragraph 3 and are not presented as a complete solution.', '']
    },
    {
      type: 'Application', title: 'Which practice best follows the author’s recommendation?', correct: 1,
      options: ['Adding every available data layer to a map without distinguishing its intended uses.', 'Publishing an accessibility map with a clear scope and a way to correct unusable routes.', 'Labelling a resident-created map neutral because all its contributors live locally.', 'Withdrawing a useful transport map because it does not describe every neighbourhood.'],
      rationale: 'A stated scope makes the purpose visible. Correcting unusable routes keeps the map open to revision and accountable to the people depending on it.',
      wrong: ['This repeats the accumulation-of-detail approach that paragraph 2 questions, without clarifying the map’s purpose.', '', 'Local contributors still choose categories and may leave people unheard; residence does not confer neutrality.', 'The author rejects treating incompleteness as a reason to dismiss every map. A useful map can be limited and still valuable.']
    },
    {
      type: 'Author’s stance', title: 'Which description best captures the author’s attitude towards maps?', correct: 2,
      options: ['Dismissive of their usefulness because they simplify complex experiences.', 'Confident that participatory methods can eliminate their limitations.', 'Critical of claims to completeness, but attentive to their practical value.', 'Concerned mainly with improving the visual detail of official maps.'],
      rationale: 'The author acknowledges the usefulness of abstraction, questions completeness and neutrality, and ends with a standard grounded in practical consequences.',
      wrong: ['The opening calls abstraction useful, and the conclusion retains a concrete role for maps.', 'The author explicitly identifies choices and exclusions within participatory projects.', '', 'Visual detail is only one part of the discussion. Purpose, participation and the effects of omissions are central.']
    },
    {
      type: 'Evidence & reasoning', title: 'Why does the author introduce the wheelchair user’s route?', correct: 0,
      options: ['To show that an incomplete map can still be assessed against a practical promise.', 'To argue that accessibility is the only valid purpose for producing a map.', 'To establish that community maps provide more accurate routes than official ones.', 'To suggest that explaining a map’s limitations excuses errors in its directions.'],
      rationale: 'The example makes accountability concrete: an advertised accessible route should be usable. Partiality does not make every map equally untrustworthy or excuse a failed promise.',
      wrong: ['', 'The example illustrates a principle; the passage does not restrict legitimate mapping to accessibility.', 'No comparison of official and community route accuracy is made in this example.', 'The passage states the reverse: incompleteness does not excuse a broken promise.']
    },
    {
      type: 'Detail (except)', title: 'Each of the following is presented in the passage as a limitation of maps or mapping, EXCEPT:', correct: 3,
      options: ['A transport map rarely shows what a journey costs the passenger.', 'The timing of a mapping meeting can shut out the people whose routes are least understood.', 'Conflicting accounts of one place cannot always be captured by a single symbol.', 'Official maps are revised too slowly to keep pace with a changing city.'],
      rationale: 'The passage never discusses how quickly maps are updated. Revision appears only in paragraph 4, as a quality of a useful map, not as a failing of official ones.',
      wrong: ['Paragraph 1 says a transport map rarely records the cost of a fare.', 'Paragraph 3 notes that a weekday-afternoon meeting may exclude workers whose routes are least understood.', 'Paragraph 2 says differing accounts cannot always be reduced to a single symbol.', '']
    },
    {
      type: 'Assumption', title: 'The claim that a map’s incompleteness “does not excuse a broken promise” depends on which assumption?', correct: 1,
      options: ['A trustworthy map must disclose every one of its omissions to its users.', 'What a map sets out to do creates a commitment its users can reasonably rely on.', 'Wheelchair users depend on maps more heavily than other residents do.', 'Community maps are more likely than official maps to break such promises.'],
      rationale: 'For an omission to count as a broken promise, the map’s stated purpose must bind it. The author assumes that declaring a purpose, such as showing accessible routes, creates that obligation.',
      wrong: ['Too strong. The author asks only whether an omission conceals a limitation that matters, not that every omission be disclosed.', '', 'The argument needs no comparison between groups of users; the example simply makes the principle concrete.', 'The passage makes no comparison of how often different kinds of maps fail their users.']
    }
  ];
  const total = questions.length;
  const pad = (n) => String(n).padStart(2, '0');
  const state = { current: 0, choices: Array(questions.length).fill(null), checked: Array(questions.length).fill(false) };
  const themeButton = $('#theme');
  function labelTheme() {
    const isDark = document.documentElement.dataset.theme === 'dark';
    themeButton.setAttribute('aria-label', `Switch to ${isDark ? 'light' : 'dark'} theme`);
    themeButton.setAttribute('aria-pressed', String(isDark));
    $('meta[name="theme-color"]').content = isDark ? '#141a24' : '#f7f7f2';
  }
  themeButton.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('pw-theme', next); } catch (_) {}
    labelTheme();
  });
  labelTheme();
  const menu = $('.menu-toggle');
  const nav = $('#navigation');
  function closeMenu() { menu.setAttribute('aria-expanded', 'false'); nav.classList.remove('is-open'); }
  menu.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open)); nav.classList.toggle('is-open', open);
  });
  nav.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && nav.classList.contains('is-open')) { closeMenu(); menu.focus(); }
  });
  document.querySelectorAll('[data-interest]').forEach((link) => link.addEventListener('click', () => {
    $('#interest').value = link.dataset.interest;
  }));
  function renderFeedback() {
    const question = questions[state.current];
    const choice = state.choices[state.current];
    const feedback = $('#feedback');
    feedback.replaceChildren();
    feedback.hidden = !state.checked[state.current];
    if (feedback.hidden) return;
    const correct = choice === question.correct;
    const title = document.createElement('strong');
    title.textContent = correct ? `Correct — ${letters[question.correct]}` : `The best answer is ${letters[question.correct]}`;
    const rationale = document.createElement('p'); rationale.textContent = question.rationale;
    feedback.append(title, rationale);
    if (!correct) { const why = document.createElement('p'); why.textContent = `Why ${letters[choice]} falls short: ${question.wrong[choice]}`; feedback.append(why); }
  }
  // With eight questions, prev/next alone is slow; the strip lets faculty jump and see what they've checked.
  function renderDots() {
    const dots = $('#question-dots'); dots.replaceChildren();
    questions.forEach((question, index) => {
      const dot = document.createElement('button'); dot.type = 'button'; dot.className = 'question-dot'; dot.textContent = String(index + 1);
      let status = 'not checked';
      if (state.checked[index]) {
        const right = state.choices[index] === question.correct;
        dot.classList.add(right ? 'is-correct' : 'is-incorrect'); status = right ? 'correct' : 'incorrect';
      }
      if (index === state.current) { dot.classList.add('is-current'); dot.setAttribute('aria-current', 'step'); }
      dot.setAttribute('aria-label', `Question ${index + 1}, ${status}`);
      dot.addEventListener('click', () => { if (index !== state.current) { state.current = index; renderQuestion(true); } });
      dots.append(dot);
    });
  }
  function renderQuestion(focus = false) {
    const question = questions[state.current];
    $('#question-type').textContent = question.type.toUpperCase();
    $('#question-title').textContent = question.title;
    $('#question-title').tabIndex = -1;
    $('#question-count').textContent = `${pad(state.current + 1)} / ${pad(total)}`;
    renderDots();
    const options = $('#options'); options.replaceChildren();
    question.options.forEach((text, index) => {
      const label = document.createElement('label'); label.className = 'option';
      const input = document.createElement('input'); input.type = 'radio'; input.name = 'answer'; input.value = String(index);
      input.checked = state.choices[state.current] === index; input.disabled = state.checked[state.current];
      input.addEventListener('change', () => { state.choices[state.current] = index; $('#check-answer').disabled = false; });
      const letter = document.createElement('span'); letter.className = 'option-letter'; letter.textContent = letters[index]; letter.setAttribute('aria-hidden', 'true');
      const content = document.createElement('span'); content.textContent = text;
      label.append(input, letter, content);
      if (state.checked[state.current]) {
        if (index === question.correct) label.classList.add('is-correct');
        else if (index === state.choices[state.current]) label.classList.add('is-incorrect');
      }
      options.append(label);
    });
    $('#check-answer').disabled = state.choices[state.current] === null || state.checked[state.current];
    $('#check-answer').firstChild.textContent = state.checked[state.current] ? 'Answer checked ' : 'Check answer ';
    $('#previous-question').disabled = state.current === 0;
    $('#next-question').disabled = state.current === questions.length - 1;
    const count = state.checked.filter(Boolean).length;
    const score = state.checked.reduce((total, checked, index) => total + (checked && state.choices[index] === questions[index].correct ? 1 : 0), 0);
    $('#quiz-score').textContent = count === total ? `${score} of ${total} correct` : `${count} of ${total} checked`;
    renderFeedback();
    if (focus) $('#question-title').focus({ preventScroll: true });
  }
  $('#check-answer').addEventListener('click', () => {
    if (state.choices[state.current] === null || state.checked[state.current]) return;
    state.checked[state.current] = true; renderQuestion();
    $('#feedback').tabIndex = -1; $('#feedback').focus({ preventScroll: true });
  });
  $('#previous-question').addEventListener('click', () => { if (state.current > 0) { state.current--; renderQuestion(true); } });
  $('#next-question').addEventListener('click', () => { if (state.current < questions.length - 1) { state.current++; renderQuestion(true); } });
  $('#reset-quiz').addEventListener('click', () => { state.current = 0; state.choices.fill(null); state.checked.fill(false); renderQuestion(true); });
  renderQuestion();
  const form = $('#enquiry-form');
  function enquiryBody(data) {
    return ['Hello Passage Works,', '', `I’m interested in: ${data.get('interest')}`, '', `Name: ${String(data.get('name')).trim()}`, `Work email: ${String(data.get('email')).trim()}`, `Organisation: ${String(data.get('organisation')).trim()}`, '', 'Our content brief:', String(data.get('brief')).trim() || 'I would like to discuss our requirements.', '', 'Please share the next steps.'].join('\n');
  }
  $('#whatsapp-enquiry').addEventListener('click', () => {
    if (!form.reportValidity()) return;
    const body = enquiryBody(new FormData(form));
    $('#prepared-brief').value = body;
    $('#enquiry-result').hidden = false;
    $('#enquiry-status').textContent = 'Your WhatsApp message is ready. If WhatsApp did not open, copy your brief and message +91 83192 30930.';
    window.open(`https://wa.me/918319230930?text=${encodeURIComponent(body)}`, '_blank', 'noopener');
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const body = enquiryBody(data);
    $('#prepared-brief').value = body;
    $('#enquiry-result').hidden = false;
    $('#enquiry-status').textContent = 'Your email draft is ready. If your email app did not open, copy your brief and email it to ansh@passageworks.in.';
    const subject = `Passage Works enquiry: ${data.get('interest')}`;
    window.location.href = `mailto:ansh@passageworks.in?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  });
  $('#copy-enquiry').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('#prepared-brief').value);
      $('#enquiry-status').textContent = 'Enquiry copied. Paste it into an email to ansh@passageworks.in and send when you’re ready.';
    } catch (_) {
      $('#prepared-brief').focus(); $('#prepared-brief').select();
      $('#enquiry-status').textContent = 'Your brief is selected. Copy it and paste it into an email to ansh@passageworks.in.';
    }
  });
})();
