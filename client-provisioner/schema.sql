create database pvcprov owner pvcprov;
\c pvcprov
create table system_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, vcpu_count INT NOT NULL, vram_mb INT NOT NULL, serial BOOL NOT NULL, vnc BOOL NOT NULL, vnc_bind TEXT, node_limit TEXT, node_selector TEXT, start_with_node BOOL NOT NULL);
create table network_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, mac_template TEXT);
create table network (id SERIAL PRIMARY KEY, network_template INT REFERENCES network_template(id), vni INT NOT NULL);
create table storage_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);
create table storage (id SERIAL PRIMARY KEY, storage_template INT REFERENCES storage_template(id), pool TEXT NOT NULL, disk_id TEXT NOT NULL, disk_size_gb INT NOT NULL, mountpoint TEXT, filesystem TEXT, filesystem_args TEXT);
create table userdata_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, userdata TEXT NOT NULL);
create table script (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, script TEXT NOT NULL);
create table profile (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, system_template INT REFERENCES system_template(id), network_template INT REFERENCES network_template(id), storage_template INT REFERENCES storage_template(id), userdata_template INT REFERENCES userdata_template(id), script INT REFERENCES script(id), arguments text);
grant all privileges on database pvcprov to pvcprov;
grant all privileges on all tables in schema public to pvcprov;
grant all privileges on all sequences in schema public to pvcprov;

insert into userdata_template(name, userdata) values ('empty', '');
