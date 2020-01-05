CREATE TABLE system_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, vcpu_count INT NOT NULL, vram_mb INT NOT NULL, serial BOOL NOT NULL, vnc BOOL NOT NULL, vnc_bind TEXT, node_limit TEXT, node_selector TEXT, node_autostart BOOL NOT NULL);
CREATE TABLE network_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, mac_template TEXT);
CREATE TABLE network (id SERIAL PRIMARY KEY, network_template INT REFERENCES network_template(id), vni INT NOT NULL);
CREATE TABLE storage_template (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE storage (id SERIAL PRIMARY KEY, storage_template INT REFERENCES storage_template(id), pool TEXT NOT NULL, disk_id TEXT NOT NULL, disk_size_gb INT NOT NULL, mountpoint TEXT, filesystem TEXT, filesystem_args TEXT);
CREATE TABLE userdata (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, userdata TEXT NOT NULL);
CREATE TABLE script (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, script TEXT NOT NULL);
CREATE TABLE profile (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, system_template INT REFERENCES system_template(id), network_template INT REFERENCES network_template(id), storage_template INT REFERENCES storage_template(id), userdata INT REFERENCES userdata(id), script INT REFERENCES script(id), arguments text);

INSERT INTO userdata (name, userdata) VALUES ('empty', '');
INSERT INTO script (name, script) VALUES ('empty', '');
