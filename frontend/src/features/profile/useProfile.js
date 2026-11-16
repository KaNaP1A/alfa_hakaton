import { useCallback, useRef, useState } from 'react';
import { api } from '../../shared/api/index.js';
import { cleanProfile,emptyProfile } from './storage.js';
import { createProfileUpdateQueue } from './profileUpdateQueue.js';
export function useProfile(){
  const [profile,setProfile]=useState(emptyProfile);
  const [history,setHistory]=useState([]);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const writes=useRef(null);
  if (!writes.current) writes.current=createProfileUpdateQueue();
  const refresh=useCallback(async()=>{
    setLoading(true);setError('');
    try{const [user,events]=await Promise.all([api.me(),api.events()]);setProfile(cleanProfile(user.profile));setHistory(events.items||[]);return user;}
    catch(e){setError(e.message);throw e;}finally{setLoading(false)}
  },[]);
  function saveProfile(data){
    const payload=cleanProfile(data);
    return writes.current.run(async()=>{const updated=await api.updateProfile(payload);setProfile(cleanProfile(updated));return updated;});
  }
  function waitForSaves(){return writes.current.waitForIdle();}
  async function addActivity(item,action,generation,position=null){
    if(!generation||!item?.entity_key)throw Error('Нет идентификатора материала или версии каталога.');
    const event_id=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
    await api.addEvent({generation,event_id,entity_key:item.entity_key,action,position});
    const updated=await api.events();setHistory(updated.items||[]);
  }
  function clear(){setProfile(emptyProfile());setHistory([]);setError('');}
  const viewed=history.filter(x=>x.action==='viewed').map(x=>x.entity_key);
  const completed=history.filter(x=>x.action==='completed').map(x=>x.entity_key);
  return {profile,history,viewed,completed,loading,error,refresh,saveProfile,waitForSaves,addActivity,clear};
}
