export const dashboardViewTemplate = `
  <section class="hero-strip">
    <h2>污水排放批总览</h2>
    <p>采样入库 → 超标挂起 → 准排裁定 → 封批升代 → 许可对账</p>
  </section>
  <div class="stats">
    <div class="stat"><div class="n">{{ dash.plants || 0 }}</div><div class="l">处理厂</div></div>
    <div class="stat"><div class="n">{{ dash.outfalls || 0 }}</div><div class="l">排放口</div></div>
    <div class="stat"><div class="n">{{ dash.samples || 0 }}</div><div class="l">采样批次</div></div>
    <div class="stat"><div class="n">{{ dash.open_exceeds || 0 }}</div><div class="l">开放超标</div></div>
    <div class="stat"><div class="n">{{ dash.discharge_releases || 0 }}</div><div class="l">已准排</div></div>
    <div class="stat"><div class="n">{{ dash.discharge_seals || 0 }}</div><div class="l">已封批</div></div>
    <div class="stat"><div class="n">{{ dash.permits || 0 }}</div><div class="l">许可册</div></div>
    <div class="stat"><div class="n">{{ dash.side_pending || 0 }}</div><div class="l">旁路挂起</div></div>
  </div>
    <div class="panel">
      <h3>日切日流量（与对账/采样/排放口/处理厂同源）</h3>
      <div class="kv">
        <span>日切日</span><span>{{ daycut.day || "—" }}</span>
        <span>日切状态</span><span :class="daycut.status==='关闭'?'fail':'pass'">{{ daycut.status || "—" }}</span>
        <span>正式日流量 m3/d</span><span>{{ daycut.formal_flow_m3 }}</span>
        <span>影子草案 m3/d</span><span>{{ daycut.draft_flow_m3 }}</span>
        <span>样本数</span><span>{{ daycut.sample_count }}</span>
      </div>
      <p v-if="daycut.minutes" class="muted">{{ daycut.minutes }}</p>
    </div>
    <div class="panel">
      <h3>产品骨架</h3>
      <p class="muted">{{ (dash.meta && dash.meta.skeleton) || "—" }}</p>
    </div>`;
