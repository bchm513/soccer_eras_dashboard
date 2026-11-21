// One floating tooltip shared by every panel.
const tip = document.getElementById("tip");
export const showTip = (e, html) => {
  tip.innerHTML = html;
  tip.hidden = false;
  tip.style.left = e.clientX + 12 + "px";
  tip.style.top = e.clientY + 12 + "px";
};
export const hideTip = () => { tip.hidden = true; };
