// =======================================
// CYBERFORGE PACKET SNIFFER
// packet_sniffer.js
// =======================================

let captureRunning = false;

let refreshTimer = null;

//========================================
// BUTTONS
//========================================

const startBtn = document.getElementById("start-btn");

const stopBtn = document.getElementById("stop-btn");

const clearBtn = document.getElementById("clear-btn");

const exportBtn = document.getElementById("export-btn");

const filter = document.getElementById("protocol-filter");

const search = document.getElementById("search");

//========================================
// START CAPTURE
//========================================

startBtn.addEventListener("click", startCapture);

async function startCapture(){

    if(captureRunning)
        return;

    captureRunning=true;

    document.getElementById("capture-status").innerHTML="🟢 Capturing";

    await fetch("/api/start_capture",{

        method:"POST"

    });

    refreshTimer=setInterval(loadPackets,1000);

}

//========================================
// STOP CAPTURE
//========================================

stopBtn.addEventListener("click",stopCapture);

async function stopCapture(){

    captureRunning=false;

    document.getElementById("capture-status").innerHTML="🔴 Stopped";

    clearInterval(refreshTimer);

    await fetch("/api/stop_capture",{

        method:"POST"

    });

}

//========================================
// CLEAR TABLE
//========================================

clearBtn.addEventListener("click",()=>{

    document.getElementById("packet-body").innerHTML="";

    document.getElementById("packet-count").innerText=0;

    document.getElementById("tcp-count").innerText=0;

    document.getElementById("udp-count").innerText=0;

    document.getElementById("speed").innerText="0 KB/s";

});

//========================================
// EXPORT
//========================================

exportBtn.addEventListener("click",()=>{

    window.location="/api/export_capture";

});

//========================================
// LOAD LIVE PACKETS
//========================================

async function loadPackets(){

    let protocol=filter.value;

    let keyword=search.value;

    const response=await fetch(

        "/api/live_packets?protocol="+protocol+"&search="+keyword

    );

    const packets=await response.json();

    renderPackets(packets);

}

//========================================
// RENDER TABLE
//========================================

function renderPackets(packetList){

    const body=document.getElementById("packet-body");

    body.innerHTML="";

    let tcp=0;

    let udp=0;

    packetList.forEach(packet=>{

        if(packet.protocol==="TCP") tcp++;

        if(packet.protocol==="UDP") udp++;

        const row=document.createElement("tr");

        row.innerHTML=`

        <td>${packet.time}</td>

        <td>${packet.src}</td>

        <td>${packet.dst}</td>

        <td>${packet.protocol}</td>

        <td>${packet.port}</td>

        <td>${packet.length}</td>

        <td>${packet.info}</td>

        `;

        row.onclick=()=>showPacket(packet);

        body.appendChild(row);

    });

    document.getElementById("packet-count").innerText=packetList.length;

    document.getElementById("tcp-count").innerText=tcp;

    document.getElementById("udp-count").innerText=udp;

    document.getElementById("speed").innerText=(packetList.length*2)+" KB/s";

}

//========================================
// SHOW DETAILS
//========================================

function showPacket(packet){

document.getElementById("packet-details").textContent=

`Timestamp : ${packet.time}

Source IP : ${packet.src}

Destination IP : ${packet.dst}

Protocol : ${packet.protocol}

Port : ${packet.port}

Length : ${packet.length}

Information :

${packet.info}`;

document.getElementById("hex-viewer").textContent=

packet.hex;

}

//========================================
// FILTER
//========================================

filter.addEventListener("change",()=>{

if(captureRunning)

loadPackets();

});

//========================================
// SEARCH
//========================================

search.addEventListener("keyup",()=>{

if(captureRunning)

loadPackets();

});

//========================================
// AUTO LOAD
//========================================

window.onload=function(){

document.getElementById("capture-status").innerHTML="⚪ Idle";

}