"""Controlled dynamic Easy Apply form; never sends a job application."""

BODY = """<!doctype html><html><head><meta charset="utf-8"><title>Task 22</title>
<style>body{font-family:Arial;margin:40px}dialog{width:480px;padding:24px}
button{margin:12px;padding:10px}label{display:block;margin:12px}</style></head><body>
<ul class="jobs-search__results-list"><li class="jobs-search-results__list-item">
<div class="base-search-card__title">Engineer</div>
<div class="base-search-card__subtitle">Example</div>
<div id="card-status">Viewed · Easy Apply</div></li></ul>
<dialog open id="application"><h2>Apply to Example</h2><h3 id="heading">Contact</h3>
<section id="contact"><label for="answer">Availability *</label>
<input id="answer" required>
<button type="button" id="next">Next</button></section>
<section id="resume" hidden><p>Resume</p><label>
<input type="radio" name="resume" value="resume.pdf">resume.pdf</label>
<button type="button" id="review">Review</button></section>
<section id="intermediate" hidden><p id="review-text"></p>
<button type="button" id="continue">Continue</button></section>
<section id="terminal" hidden><p>Review your application</p>
<button type="button" id="submit">Submit application</button></section></dialog>
<dialog id="confirmation"><h2>Application submitted</h2>
<button id="done" type="button">Done</button></dialog>
<script>
window.submitClicks=0; window.errors=[];
window.addEventListener('error', e => errors.push(e.message));
const app=document.getElementById('application');
const heading=document.getElementById('heading');
const params=new URLSearchParams(location.search);
let reviews=Number(params.get('reviews') || '0');
function step(name) {
  ['contact','resume','intermediate','terminal'].forEach(id=>
    document.getElementById(id).hidden=id!==name);
  heading.textContent=name==='terminal'?'Final review':name;
}
document.getElementById('next').onclick=()=>step('resume');
function review() {
  if (reviews-- > 0) {
    document.getElementById('review-text').textContent='Review section '+reviews;
    step('intermediate');
  } else step('terminal');
}
document.getElementById('review').onclick=review;
document.getElementById('continue').onclick=review;
document.getElementById('submit').onclick=()=> {
  window.submitClicks++;
  if (params.get('missing')) return;
  app.close();
  document.getElementById('card-status').textContent='Applied · Easy Apply';
  document.getElementById('confirmation').showModal();
};
document.getElementById('done').onclick=()=>document.getElementById('confirmation').close();
</script></body></html>"""
