# syntax=docker/dockerfile:1
FROM ubuntu:20.04
LABEL Description="CORE Docker Image"

# define variables
ARG DEBIAN_FRONTEND=noninteractive
ARG PREFIX=/usr/local
ARG BRANCH=master
ARG CORE_TARBALL=core.tar.gz
ARG OSPF_TARBALL=ospf.tar.gz

# 设置中国时区
RUN rm -rf /etc/localtime
RUN ln -s /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

# install system dependencies
RUN sed -i s@/archive.ubuntu.com/@/mirrors.aliyun.com/@g /etc/apt/sources.list && \
    apt-get clean && \
    apt-get -y update && \
    apt-get install -y --no-install-recommends \
    vim \
    automake \
    bash \
    ca-certificates \
    ethtool \
    gawk \
    gcc \
    g++ \
    iproute2 \
    iputils-ping \
    libc-dev \
    libev-dev \
    libreadline-dev \
    libtool \
    libtk-img \
    make \
    nftables \
    python3 \
    python3-pip \
    python3-tk \
    pkg-config \
    tk \
    wget \
    xauth \
    xterm \
    ssh \
    psmisc \
    && apt-get clean

RUN pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple \
    && pip3 config set install.trusted-host mirrors.aliyun.com

# install python dependencies
RUN python3 -m pip install \
    grpcio==1.27.2 \
    grpcio-tools==1.27.2 \
    poetry==1.1.7 \
    ipython==7.30.1 \
    supervisor==4.2.4

# retrieve, build, and install core
RUN wget -q -O ${CORE_TARBALL} https://api.github.com/repos/coreemu/core/tarball/${BRANCH} && \
    tar xf ${CORE_TARBALL} && \
    cd coreemu-core* && \
    ./bootstrap.sh && \
    ./configure && \
    make -j $(nproc) && \
    make install && \
    cd daemon && \
    python3 -m poetry build -f wheel && \
    python3 -m pip install dist/* && \
    cp scripts/* ${PREFIX}/bin && \
    mkdir /etc/core && \
    cp -n data/core.conf /etc/core && \
    cp -n data/logging.conf /etc/core && \
    mkdir -p ${PREFIX}/share/core && \
    cp -r examples ${PREFIX}/share/core && \
    echo '\
[Unit]\n\
Description=Common Open Research Emulator Service\n\
After=network.target\n\
\n\
[Service]\n\
Type=simple\n\
ExecStart=/usr/local/bin/core-daemon\n\
TasksMax=infinity\n\
\n\
[Install]\n\
WantedBy=multi-user.target\
' > /lib/systemd/system/core-daemon.service && \
    cd ../.. && \
    rm ${CORE_TARBALL} && \
    rm -rf coreemu-core*
# retrieve, build, and install ospf mdr
RUN wget -q -O ${OSPF_TARBALL} https://github.com/USNavalResearchLaboratory/ospf-mdr/tarball/master && \
    tar xf ${OSPF_TARBALL} && \
    cd USNavalResearchLaboratory-ospf-mdr* && \
    ./bootstrap.sh && \
    ./configure --disable-doc --enable-user=root --enable-group=root \
        --with-cflags=-ggdb --sysconfdir=/usr/local/etc/quagga --enable-vtysh \
        --localstatedir=/var/run/quagga && \
    make -j $(nproc) && \
    make install && \
    cd .. && \
    rm ${OSPF_TARBALL} && \
    rm -rf USNavalResearchLaboratory-ospf-mdr*

# retrieve and install emane packages
RUN wget -q https://adjacentlink.com/downloads/emane/emane-1.2.7-release-1.ubuntu-20_04.amd64.tar.gz && \
    tar xf emane*.tar.gz && \
    cd emane-1.2.7-release-1/debs/ubuntu-20_04/amd64 && \
    apt-get install -y ./emane*.deb ./python3-emane_*.deb && \
    cd ../../../.. && \
    rm emane-1.2.7-release-1.ubuntu-20_04.amd64.tar.gz && \
    rm -rf emane-1.2.7-release-1

# supervisor
RUN touch /tmp/supervisor.sock && \
    # 生成supervisor配置文件
    echo_supervisord_conf > /etc/supervisord.conf && \
    # http://supervisord.org/configuration.html#include-section-settings
    echo "[include]" >> /etc/supervisord.conf && \
    echo "files = supervisord.d/*.ini" >> /etc/supervisord.conf && \
    echo "" >> /etc/supervisord.conf && \
    # 在前台运行supervisord http://supervisord.org/configuration.html#supervisord-section-settings
    echo "[supervisord]" >> /etc/supervisord.conf && \
    echo "nodaemon=true" >> /etc/supervisord.conf && \
    echo "" >> /etc/supervisord.conf && \
    # core-daemon配置
    echo "[program:core-daemon]" >> /etc/supervisord.conf && \
    echo "command=core-daemon" >> /etc/supervisord.conf && \
    echo "process_name=%(program_name)s ; process_name expr (default %(program_name)s)" >> /etc/supervisord.conf && \
    echo "numprocs=1                    ; number of processes copies to start (def 1)" >> /etc/supervisord.conf && \
    echo "umask=022                     ; umask for process (default None)" >> /etc/supervisord.conf && \
    echo "priority=999                  ; the relative start priority (default 999)" >> /etc/supervisord.conf && \
    echo "autostart=true                ; start at supervisord start (default: true)" >> /etc/supervisord.conf && \
    echo "autorestart=true              ; retstart at unexpected quit (default: true)" >> /etc/supervisord.conf && \
    echo "startsecs=10                  ; number of secs prog must stay running (def. 1)" >> /etc/supervisord.conf && \
    echo "startretries=3                ; max # of serial start failures (default 3)" >> /etc/supervisord.conf && \
    echo "exitcodes=0,2                 ; 'expected' exit codes for process (default 0,2)" >> /etc/supervisord.conf && \
    echo "stopsignal=QUIT               ; signal used to kill process (default TERM)" >> /etc/supervisord.conf && \
    echo "stopwaitsecs=10               ; max num secs to wait b4 SIGKILL (default 10)" >> /etc/supervisord.conf && \
    echo "user=root                   ; setuid to this UNIX account to run the program" >> /etc/supervisord.conf && \
    echo "stderr_logfile=/var/log/core-daemon-err.log        ; stderr log path, NONE for none; default AUTO" >> /etc/supervisord.conf && \
    echo "stdout_logfile=/var/log/core-daemon-out.log        ; stdout log path, NONE for none; default AUTO" >> /etc/supervisord.conf

RUN mkdir -p /root/.coregui/scripts

COPY ./daemon/examples /root/.coregui/scripts

CMD supervisord -c /etc/supervisord.conf

# tag 2022.3.30 systemctl改用supervisor
