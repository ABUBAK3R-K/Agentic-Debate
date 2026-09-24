/** When a debate or persona was made, in the reader's own locale. */
export const dateFormat = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

/**
 * Public figures as [category, people] pairs. The API already sends them in
 * display order, so categories keep the order they first appear in.
 */
export function groupByCategory(people) {
  const groups = new Map();
  for (const person of people) {
    const key = person.category || 'Other';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(person);
  }
  return [...groups];
}
