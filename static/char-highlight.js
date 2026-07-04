(function(){
var content = document.getElementById('post-content');
if (!content) return;
var summary = document.getElementById('post-summary');
var limit = parseInt(content.getAttribute('data-max-length') || 500, 10);

var wrap = document.createElement('div');
wrap.className = 'textarea-wrap';
content.parentNode.insertBefore(wrap, content);
var highlight = document.createElement('pre');
highlight.className = 'textarea-highlight';
highlight.setAttribute('aria-hidden','true');
wrap.appendChild(highlight);
wrap.appendChild(content);
content.style.background = 'transparent';
content.style.position = 'relative';
content.style.zIndex = '2';

function sync() {
  var total = (content.value.length) + (summary ? summary.value.length : 0);
  var contentLimit = Math.max(0, limit - (summary ? summary.value.length : 0));
  var txt = content.value;
  var before = txt.slice(0, contentLimit);
  var after = txt.slice(contentLimit);
  highlight.innerHTML = '';
  if (before) {
    var s = document.createElement('span');
    s.textContent = before;
    highlight.appendChild(s);
  } else if (txt) {
    // all overflow
  }
  if (after) {
    var m = document.createElement('mark');
    m.textContent = after;
    highlight.appendChild(m);
    content.classList.add('has-overflow');
  } else {
    content.classList.remove('has-overflow');
  }
  highlight.scrollTop = content.scrollTop;
  highlight.scrollLeft = content.scrollLeft;
}

content.addEventListener('scroll', function(){ highlight.scrollTop = content.scrollTop; highlight.scrollLeft = content.scrollLeft; });
content.addEventListener('input', sync);
if (summary) summary.addEventListener('input', sync);
var form = content.form;
if (form) {
  form.addEventListener('submit', function(e) {
    var total = content.value.length + (summary ? summary.value.length : 0);
    if (total <= limit) return;
    e.preventDefault();
    var submit = form.querySelector('button[type="submit"]');
    wrap.classList.remove('shake');
    void wrap.offsetWidth;
    wrap.classList.add('shake');
    if (submit) submit.classList.add('over-limit-submit');
    content.focus();
  });
}
sync();
})();
