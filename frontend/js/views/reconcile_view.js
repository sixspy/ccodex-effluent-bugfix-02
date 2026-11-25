export const reconcileViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>许可对账</h3>
      <div class="actions"><button class="secondary" @click="loadReconcile">刷新全部</button></div>
      <div class="kv">
        <span>日切日</span><span>{{ daycut.day || "—" }}</span>
        <span>日切状态</span><span :class="daycut.status==='关闭'?'fail':'pass'">{{ daycut.status || "—" }}</span>
        <span>正式日流量 m3/d</span><span>{{ daycut.formal_flow_m3 }}</span>
        <span>影子草案 m3/d</span><span>{{ daycut.draft_flow_m3 }}</span>
      </div>
      <p v-if="daycut.status==='关闭'" class="muted">
        日切已关闭：正式区流量零改，修订请落影子草案，解封后原子升正。
      </p>
      <table>
        <thead><tr><th>许可</th><th>对齐</th><th>证明</th><th>封批数</th><th>累计日流量 m3</th></tr></thead>
        <tbody>
          <tr v-for="r in reconAllItems" :key="r.permit_code">
            <td>{{ r.permit_code }}</td>
            <td :class="r.balanced?'pass':'fail'">{{ r.balanced ? "齐" : "不齐" }}</td>
            <td :class="r.proof_ready?'pass':'warn'">{{ r.proof_ready ? "可证" : "未齐" }}</td>
            <td>{{ r.seal_count || 0 }}</td>
            <td>{{ r.cumulative_flow_m3 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>单许可 / 采样证明</h3>
      <label>许可号</label><input v-model="reconCode"/>
      <div class="actions"><button @click="loadReconcileOne">对账</button></div>
      <pre v-if="reconOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(reconOne, null, 2) }}</pre>
      <label>采样号证明</label><input v-model="proofCode"/>
      <div class="actions"><button class="secondary" @click="loadProof">证明</button></div>
      <pre v-if="proofOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(proofOne, null, 2) }}</pre>
    </div>
  </div>`;
