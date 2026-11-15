'use strict';
// Minimal same-origin client for the synthetic local server. Do not use as the production API contract.
const form = document.querySelector('#search');
const results = document.querySelector('#results');
const status = document.querySelector('#status');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const params = new URLSearchParams({q: new FormData(form).get('q'), mode: 'relevance'});
  status.textContent = 'Загрузка…';
  results.replaceChildren();
  try {
    const response = await fetch(`/search?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Ошибка запроса');
    status.textContent = data.results.length ? `Результатов: ${data.results.length}` : 'Ничего не найдено';
    if (data.clarification) {
      const question = document.createElement('p');
      question.textContent = data.clarification.question;
      results.append(question);
    }
    for (const item of data.results) {
      const card = document.createElement('article');
      const title = document.createElement('h2');
      const description = document.createElement('p');
      title.textContent = item.title;
      description.textContent = item.promotion?.text || item.description || '';
      card.append(title, description);
      results.append(card);
    }
  } catch (error) {
    status.textContent = `Не удалось получить ответ: ${error.message}`;
  }
});
