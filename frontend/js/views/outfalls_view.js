export const outfallsViewTemplate = `
  <div class="grid-2">
    <div class="panel">
      <h3>排放口限值</h3>
      <table>
        <thead><tr><th>编码</th><th>厂</th><th>河段</th><th>COD</th><th>氨氮</th><th>总磷</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="o in outfalls" :key="o.id" @click="loadOutfall(o.id)" style="cursor:pointer">
            <td>{{ o.outfall_code }}</td><td>{{ o.plant_code }}</td><td>{{ o.river_reach }}</td>
            <td>{{ o.cod_limit }}</td><td>{{ o.nh3n_limit }}</td><td>{{ o.tp_limit }}</td>
            <td :class="statusClass(o.status)">{{ o.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>新建排放口</h3>
      <div class="form-row"><div><label>编码</label><input v-model="outfallForm.outfall_code"/></div>
      <div><label>处理厂 ID</label><input type="number" v-model.number="outfallForm.plant_id"/></div></div>
      <label>河段</label><input v-model="outfallForm.river_reach"/>
      <div class="form-row">
        <div><label>COD 限</label><input type="number" v-model.number="outfallForm.cod_limit"/></div>
        <div><label>氨氮限</label><input type="number" v-model.number="outfallForm.nh3n_limit"/></div>
      </div>
      <label>总磷限</label><input type="number" v-model.number="outfallForm.tp_limit"/>
      <div class="actions"><button @click="createOutfall">登记</button></div>
      <div v-if="outfallDetail" style="margin-top:1rem">
        <h3>详情 {{ outfallDetail.outfall.outfall_code }}</h3>
        <div class="kv">
          <span>日切日</span><span>{{ outfallDetail.daycut.day || "—" }}</span>
          <span>日切状态</span><span :class="outfallDetail.daycut.status==='关闭'?'fail':'pass'">{{ outfallDetail.daycut.status || "—" }}</span>
          <span>当日正式流量 m3/d</span><span>{{ outfallDetail.daycut.formal_flow_m3 }}</span>
          <span>影子草案 m3/d</span><span>{{ outfallDetail.daycut.draft_flow_m3 }}</span>
        </div>
      </div>
    </div>
  </div>`;
